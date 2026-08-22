from datetime import date

from fnscraper import categories, config, pipeline
from fnscraper.models import Event
from fnscraper.scoring import score_event
from tests.test_scoring import make_event


def test_classify_maps_slugs_to_expected_categories():
    assert categories.category_key("Art-Shows") == "arts"
    assert categories.category_key("Fine-Art-Festivals") == "arts"
    assert categories.category_key("Craft-Shows") == "crafts"
    # Food beats the generic "festival" keyword.
    assert categories.category_key("Food-Festivals") == "food"
    assert categories.category_key("Music-Festivals") == "music"
    assert categories.category_key("Farmers-Markets") == "farmers-market"
    assert categories.category_key("Home-Garden-Shows") == "home-garden"
    assert categories.category_key("Trade-Expos") == "home-garden"
    assert categories.category_key("Holiday-Boutiques") == "holiday"
    assert categories.category_key("Fairs") == "fair"
    assert categories.category_key("State-Fair") == "fair"
    assert categories.category_key("Festivals") == "festival"
    assert categories.category_key("") == "other"
    assert categories.category_key("Something-Unknown") == "other"


def test_fairs_excluded_by_default():
    default = categories.default_selection()
    assert "fair" not in default
    assert "arts" in default and "crafts" in default and "festival" in default
    assert "fair" in categories.all_keys()


def test_normalize_keys_reports_unknown():
    valid, unknown = categories.normalize_keys(["Arts", "crafts", "bogus"])
    assert valid == {"arts", "crafts"}
    assert unknown == ["bogus"]


def test_filter_events_drops_unselected_categories():
    art = Event(event_id="1", name="Art Walk", url="u", category_slug="Art-Shows")
    fair = Event(event_id="2", name="County Fair", url="u", category_slug="Fairs")
    kept = categories.filter_events([art, fair], categories.default_selection())
    assert [e.event_id for e in kept] == ["1"]
    # None keeps everything.
    assert len(categories.filter_events([art, fair], None)) == 2


def test_filter_scored_and_present_categories():
    art = score_event(make_event(event_id="1", category_slug="Art-Shows"))
    fair = score_event(make_event(event_id="2", category_slug="Fairs"))
    craft = score_event(make_event(event_id="3", category_slug="Craft-Shows"))
    kept = categories.filter_scored([art, fair, craft], {"arts", "crafts"})
    assert {s.event.event_id for s in kept} == {"1", "3"}

    present = categories.present_categories([art, fair, craft])
    keys = [p[0] for p in present]
    # Canonical order: arts, crafts, then fair.
    assert keys == ["arts", "crafts", "fair"]
    assert dict((k, c) for k, _, c in present) == {"arts": 1, "crafts": 1, "fair": 1}


class _FakeFetcher:
    """Serves one listing page of arts/craft/fair events, then blanks."""

    def __init__(self, html):
        self._html = html

    def get(self, url):
        return self._html if url.endswith("/Ohio") else ""

    def login(self, *a, **k):
        pass

    def stats(self):
        return {"requests": 0, "cache_hits": 0, "failures": 0}


def test_pipeline_category_filter_skips_fairs(monkeypatch):
    listing = """
    <div class="festiv-block" itemscope itemtype="http://schema.org/Festival">
      <meta itemprop="startDate" content="2026-07-11"/>
      <meta itemprop="endDate" content="2026-07-11"/>
      <h2><a href="https://festivalnet.com/1/Akron-Ohio/Craft-Shows/Craft-Fest">
        <span itemprop="name">Craft Fest</span></a></h2>
      <span itemprop="location" itemscope itemtype="http://schema.org/Place">
        <span itemprop="address"><span itemprop="addressLocality">Akron</span>,
        <span itemprop="addressRegion">OH</span></span></span>
    </div>
    <div class="festiv-block" itemscope itemtype="http://schema.org/Festival">
      <meta itemprop="startDate" content="2026-07-11"/>
      <meta itemprop="endDate" content="2026-07-11"/>
      <h2><a href="https://festivalnet.com/2/Columbus-Ohio/Fairs/State-Fair">
        <span itemprop="name">State Fair</span></a></h2>
      <span itemprop="location" itemscope itemtype="http://schema.org/Place">
        <span itemprop="address"><span itemprop="addressLocality">Columbus</span>,
        <span itemprop="addressRegion">OH</span></span></span>
    </div>
    """

    monkeypatch.setattr(pipeline, "Fetcher", lambda **k: _FakeFetcher(listing))

    class _Geo:
        def __init__(self, *a, **k):
            pass

        def locate(self, city, state, address=None):
            return config.HOME_LAT, config.HOME_LON, False

        def flush(self):
            pass

    monkeypatch.setattr(pipeline, "Geocoder", _Geo)
    monkeypatch.setattr(pipeline, "drive_estimate", lambda lat, lon: (10.0, 0.2))

    today = date(2026, 7, 1)
    monkeypatch.setattr(pipeline, "date", type("D", (date,), {
        "today": classmethod(lambda cls: today)}))

    settings = config.Settings(states=["Ohio"], weeks_ahead=8,
                               categories=categories.default_selection())
    scored = pipeline.run(settings)
    names = {s.event.name for s in scored}
    assert "Craft Fest" in names
    assert "State Fair" not in names


# ---------------------------------------------------------------------------
# `best` must filter the same way whether it crawls or replays a cache
# ---------------------------------------------------------------------------

def _weekend_event(event_id: str, slug: str, name: str):
    """A show on a Saturday, near enough home to survive every other filter."""
    return make_event(
        event_id=event_id, name=name, url=f"https://festivalnet.com/{event_id}",
        category_slug=slug,
        start_date=date(2026, 7, 11), end_date=date(2026, 7, 11),
    )


def _plan_shows(tmp_path, monkeypatch, argv, today=date(2026, 7, 1)):
    """Run `fnscraper best --cached` over a two-show cache; return the names."""
    from fnscraper import cli, persist

    monkeypatch.chdir(tmp_path)
    scored = [
        score_event(_weekend_event("1", "Craft-Shows", "Craft Market")),
        score_event(_weekend_event("2", "Fairs", "County Fair")),
    ]
    persist.save_results(scored, tmp_path / "reports" / "results.json")

    class _FixedDate(date):
        @classmethod
        def today(cls):
            return today

    monkeypatch.setattr("fnscraper.best.date", _FixedDate)
    rc = cli.best_main(argv + ["--out", str(tmp_path / "export"), "--json"])
    assert rc == 0, "best returned no plan"
    return rc


def test_cached_plan_excludes_fairs_like_a_fresh_crawl(tmp_path, monkeypatch, capsys):
    """A cached plan skips the pipeline, where the category filter lives.

    Without an explicit filter on that path, `best` dropped fairs and
    `best --cached` kept them - the same command disagreeing with itself
    depending on whether it had to hit the network.
    """
    _plan_shows(tmp_path, monkeypatch, ["--cached"])
    capsys.readouterr()
    assert "County Fair" not in _exported(tmp_path)
    assert "Craft Market" in _exported(tmp_path)


def test_include_fairs_puts_them_back_on_a_cached_plan(tmp_path, monkeypatch, capsys):
    _plan_shows(tmp_path, monkeypatch, ["--cached", "--include-fairs"])
    capsys.readouterr()
    assert "County Fair" in _exported(tmp_path)


def _exported(tmp_path) -> str:
    """Everything the export wrote, as one string."""
    return "\n".join(
        p.read_text(encoding="utf-8-sig")
        for p in (tmp_path / "export").rglob("*.csv")
    )


def test_best_and_scrape_offer_the_same_category_flags():
    """The two parsers share one definition, so they cannot drift apart."""
    from fnscraper import cli

    def flags(parser):
        return {a for action in parser._actions for a in action.option_strings
                if "categor" in a or "fair" in a}

    assert flags(cli.build_best_parser()) == flags(cli.build_parser())
    assert "--include-fairs" in flags(cli.build_best_parser())

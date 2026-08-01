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

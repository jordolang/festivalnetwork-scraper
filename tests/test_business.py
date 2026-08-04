"""Per-business configuration: business.json -> config module."""

from __future__ import annotations

import importlib
import json

import pytest

from fnscraper import business, config


@pytest.fixture
def cfg(monkeypatch, tmp_path):
    """A pristine config module, restored after the test.

    The constants are process-global, so an override has to be undone or
    it poisons every test after it.  The module is also reloaded against a
    business.json that does not exist, so these tests assert against the
    shipped defaults even on a machine where the tool has been set up.
    """
    monkeypatch.setenv(business.ENV_BUSINESS_FILE, str(tmp_path / "none.json"))
    importlib.reload(config)
    saved = {k: getattr(config, k) for k in dir(config) if k.isupper()}
    yield config
    for key, value in saved.items():
        setattr(config, key, value)
    monkeypatch.undo()
    importlib.reload(config)


CANDLES = {
    "business_name": "Bayou Candle Co.",
    "home": {"city": "Austin", "state": "TX", "zip": "78701",
             "lat": 30.2713, "lon": -97.7426},
    "max_drive_hours": 6,
    "states": ["Texas", "Louisiana"],
    "product": {"unit_name": "candle", "unit_price": 18.0, "unit_cost": 6.0,
                "deal_units": 2, "deal_price": 30.0,
                "addon_price": 0.0, "addon_cost": 0.0,
                "addon_attach_rate": 0.0},
    "travel": {"mpg": 18.0, "gas_price": 3.25, "lodging_per_night": 120.0,
               "meals_per_day": 40.0},
    "planning": {"months_ahead": 3, "top_per_weekend": 4},
}


def test_no_file_keeps_the_shipped_defaults(cfg):
    business.apply(cfg, {})
    assert cfg.HOME_NAME == "Zanesville, OH"
    assert cfg.UNIT_NAME == "jar"


def test_overrides_reach_every_layer(cfg):
    business.apply(cfg, CANDLES)
    assert cfg.BUSINESS_NAME == "Bayou Candle Co."
    assert cfg.HOME_LAT == pytest.approx(30.2713)
    assert cfg.HOME_NAME == "Austin, TX"
    assert cfg.MAX_DRIVE_HOURS == 6
    assert cfg.DEFAULT_STATES == ["Texas", "Louisiana"]
    assert cfg.MPG == 18.0
    assert cfg.GAS_PRICE == 3.25
    assert cfg.BEST_MONTHS_AHEAD == 3


def test_export_dir_is_per_business(cfg):
    business.apply(cfg, CANDLES)
    # Two businesses on one machine must not write into each other's folder.
    assert cfg.BEST_EXPORT_DIR == "reports/bayou-candle-co"


def test_deal_drives_the_derived_economics(cfg):
    business.apply(cfg, CANDLES)
    assert cfg.PRICE_LADDER == [(1, 18.0), (2, 30.0)]
    assert cfg.ORDER_MIX == {2: 1.0}
    assert cfg.avg_sale() == pytest.approx(30.0)
    assert cfg.jars_per_order() == pytest.approx(2.0)
    assert cfg.cogs_per_order() == pytest.approx(12.0)


def test_avg_sale_constant_is_recomputed(cfg):
    """AVG_SALE is derived at import; a stale value would misreport revenue."""
    before = cfg.AVG_SALE
    business.apply(cfg, CANDLES)
    assert cfg.AVG_SALE != before
    assert cfg.AVG_SALE == pytest.approx(cfg.avg_sale())


def test_settings_defaults_follow_the_override(cfg):
    """Settings' dataclass defaults must not bind the shipped constants."""
    business.apply(cfg, CANDLES)
    assert config.Settings.from_env().max_drive_hours == 6
    assert config.Settings.from_env().states == ["Texas", "Louisiana"]


def test_unit_cost_wins_over_batch_economics(cfg):
    cfg.BATCH_JARS = 715              # left over from the salsa defaults
    business.apply(cfg, CANDLES)
    assert cfg.jar_cost() == pytest.approx(6.0)


def test_addon_shapes_the_average_order(cfg):
    data = json.loads(json.dumps(CANDLES))
    data["product"].update(addon_name="wick trimmer", addon_price=4.0,
                           addon_cost=1.0, addon_attach_rate=0.25)
    business.apply(cfg, data)
    assert cfg.avg_sale() == pytest.approx(30.0 + 0.25 * 4.0)
    assert cfg.cogs_per_order() == pytest.approx(12.0 + 0.25 * 1.0)


def test_deal_including_the_addon_carries_its_cost(cfg):
    data = json.loads(json.dumps(CANDLES))
    data["product"].update(addon_price=3.0, addon_cost=1.0,
                           addon_attach_rate=0.0, deal_includes_addon=True)
    business.apply(cfg, data)
    assert cfg.BUNDLE_EXTRA_COST == {2: 1.0}
    assert cfg.cogs_per_order() == pytest.approx(13.0)


def test_no_deal_means_single_item_orders(cfg):
    data = json.loads(json.dumps(CANDLES))
    data["product"].pop("deal_units")
    data["product"].pop("deal_price")
    business.apply(cfg, data)
    assert cfg.ORDER_MIX == {1: 1.0}
    assert cfg.avg_sale() == pytest.approx(18.0)


def test_advanced_block_sets_raw_constants(cfg):
    business.apply(cfg, {"advanced": {"CAPTURE_RATE": 0.02,
                                      "NOT_A_REAL_SETTING": 1}})
    assert cfg.CAPTURE_RATE == 0.02
    assert not hasattr(cfg, "NOT_A_REAL_SETTING")


def test_partial_file_leaves_the_rest_alone(cfg):
    business.apply(cfg, {"max_drive_hours": 4})
    assert cfg.MAX_DRIVE_HOURS == 4
    assert cfg.MPG == 20.0                 # untouched default
    assert cfg.BUSINESS_NAME == "Jose Madrid Salsa"


@pytest.mark.parametrize("junk", [
    {"max_drive_hours": "ten"},            # a string where a number goes
    {"max_drive_hours": -3},               # nonsense value
    {"home": "Zanesville"},                # wrong shape entirely
    {"product": None},
    {"travel": {"mpg": float("inf")}},
])
def test_bad_values_are_ignored_not_fatal(cfg, junk):
    business.apply(cfg, junk)
    assert cfg.MAX_DRIVE_HOURS == 15.0
    assert cfg.HOME_NAME == "Zanesville, OH"
    assert cfg.MPG == 20.0


def test_unreadable_file_does_not_take_the_tool_down(tmp_path, capsys):
    (tmp_path / "business.json").write_text("{not json at all", encoding="utf-8")
    assert business.load(tmp_path) == {}
    assert "WARNING" in capsys.readouterr().err


def test_save_then_load_round_trips(tmp_path):
    business.save(CANDLES, tmp_path)
    assert business.load(tmp_path) == CANDLES


def test_an_explicit_root_beats_the_env_var(tmp_path, monkeypatch):
    """Naming a directory must not be silently redirected elsewhere.

    The wizard saves into the install folder it was handed; if the env
    override won, it would overwrite whichever file that variable happens
    to point at.
    """
    decoy = tmp_path / "decoy.json"
    decoy.write_text('{"business_name": "Do Not Touch"}')
    monkeypatch.setenv(business.ENV_BUSINESS_FILE, str(decoy))

    here = tmp_path / "install"
    here.mkdir()
    business.save({"business_name": "Mine"}, here)

    assert (here / "business.json").is_file()
    assert json.loads(decoy.read_text())["business_name"] == "Do Not Touch"
    assert business.load(here)["business_name"] == "Mine"


def test_env_var_points_at_another_business(tmp_path, monkeypatch):
    elsewhere = tmp_path / "other.json"
    elsewhere.write_text(json.dumps({"business_name": "Second Booth"}))
    monkeypatch.setenv(business.ENV_BUSINESS_FILE, str(elsewhere))
    assert business.load()["business_name"] == "Second Booth"


@pytest.mark.parametrize("name,slug", [
    ("Jose Madrid Salsa", "jose-madrid-salsa"),
    ("Bayou Candle Co.", "bayou-candle-co"),
    ("  O'Brien & Sons  ", "o-brien-sons"),
    ("!!!", "business"),
])
def test_slugify(name, slug):
    assert business.slugify(name) == slug


class TestStateSelection:
    """The crawl list has to follow the business, not the original vendor."""

    def test_ohio_home_reaches_the_east(self):
        states = business.states_within(39.9403, -82.0132, 10, home_state="OH")
        assert {"Ohio", "Pennsylvania", "Kentucky", "New-York"} <= set(states)
        assert "California" not in states

    def test_texas_home_does_not_crawl_ohio(self):
        states = business.states_within(30.2713, -97.7426, 6, home_state="TX")
        assert "Texas" in states
        assert "Ohio" not in states

    def test_a_tight_radius_still_includes_the_home_state(self):
        states = business.states_within(21.3, -157.8, 0.5, home_state="OH")
        assert states == ["Ohio"]

    def test_a_wider_radius_never_shrinks_the_list(self):
        near = business.states_within(39.9403, -82.0132, 6)
        far = business.states_within(39.9403, -82.0132, 12)
        assert set(near) <= set(far)

    def test_slugs_match_festivalnet_url_style(self):
        for slug, *_ in business.STATE_TABLE:
            assert " " not in slug, f"{slug} would build a broken URL"

    def test_covers_the_drivable_states(self):
        assert len(business.STATE_TABLE) == 49       # lower 48 + DC


def test_config_import_is_side_effect_free_without_a_file(monkeypatch, tmp_path):
    """Importing config on a machine with no business.json must be a no-op."""
    monkeypatch.setenv(business.ENV_BUSINESS_FILE, str(tmp_path / "absent.json"))
    fresh = importlib.reload(config)
    try:
        assert fresh.BUSINESS == {}
        assert fresh.HOME_NAME == "Zanesville, OH"
    finally:
        monkeypatch.undo()
        importlib.reload(config)

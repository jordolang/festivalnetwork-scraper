"""The setup wizard: `python -m fnscraper setup`.

Asks a non-technical owner the dozen-odd questions the model actually
needs, then writes three files at the project root:

    business.json         home base, travel radius, product economics
    .env                  FestivalNet Pro login (kept out of git)
    vendor_profile.json   the details that go on a vendor application

Every question has a default in ``[brackets]``; pressing Enter keeps it.
Re-running the wizard pre-fills from what is already saved, so it doubles
as the "change my settings" screen and nothing has to be retyped.
"""

from __future__ import annotations

import getpass
import json
import sys
from pathlib import Path

from . import business, config, pdf_fill

ENV_FILE = ".env"

RULE = "=" * 68


# ---------------------------------------------------------------------------
# Prompting
# ---------------------------------------------------------------------------

class Cancelled(Exception):
    """The owner pressed Ctrl-C; nothing has been written."""


def _input(prompt: str) -> str:
    try:
        return input(prompt)
    except (EOFError, KeyboardInterrupt):
        raise Cancelled from None


def ask(question: str, default: str = "", *, allow_blank: bool = True) -> str:
    """A free-text question.  Enter keeps ``default``."""
    suffix = f" [{default}]" if default else ""
    while True:
        answer = _input(f"{question}{suffix}\n> ").strip() or default
        if answer or allow_blank:
            return answer
        print("  That one is required - please type something.\n")


def ask_number(question: str, default: float, *, minimum: float = 0.0,
               maximum: float | None = None, integer: bool = False) -> float:
    """A numeric question that refuses to accept nonsense."""
    shown = f"{default:g}"
    while True:
        raw = _input(f"{question} [{shown}]\n> ").strip()
        if not raw:
            return int(default) if integer else float(default)
        cleaned = raw.replace("$", "").replace(",", "").strip()
        try:
            value = float(cleaned)
        except ValueError:
            print(f"  '{raw}' isn't a number. Type digits only, e.g. {shown}\n")
            continue
        if value < minimum or (maximum is not None and value > maximum):
            top = f" and {maximum:g}" if maximum is not None else ""
            print(f"  Please enter a number between {minimum:g}{top}.\n")
            continue
        return int(round(value)) if integer else value


def ask_yes_no(question: str, default: bool) -> bool:
    hint = "Y/n" if default else "y/N"
    while True:
        raw = _input(f"{question} [{hint}]\n> ").strip().lower()
        if not raw:
            return default
        if raw in ("y", "yes"):
            return True
        if raw in ("n", "no"):
            return False
        print("  Please answer y or n.\n")


def section(title: str, blurb: str = "") -> None:
    print(f"\n{RULE}\n  {title}\n{RULE}")
    if blurb:
        print(f"{blurb}\n")


# ---------------------------------------------------------------------------
# Existing settings (so re-running never loses anything)
# ---------------------------------------------------------------------------

def _existing(root: Path) -> dict:
    data = business.load(root)
    return data if isinstance(data, dict) else {}


def _get(data: dict, path: str, fallback):
    """Nested lookup: _get(data, 'product.unit_price', 10.0)."""
    node = data
    for part in path.split("."):
        if not isinstance(node, dict) or part not in node:
            return fallback
        node = node[part]
    return fallback if node is None else node


def read_env(root: Path) -> dict[str, str]:
    path = root / ENV_FILE
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.lower().startswith("export "):
            line = line[len("export "):].lstrip()
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def write_env(root: Path, updates: dict[str, str]) -> Path:
    """Merge ``updates`` into .env, leaving any other keys alone."""
    values = read_env(root)
    values.update(updates)
    path = root / ENV_FILE
    lines = [
        "# FestivalNet Pro login. This file stays on this computer -",
        "# it is never uploaded anywhere and is excluded from git.",
    ]
    lines += [f"{k}={v}" for k, v in values.items() if v]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# The interview
# ---------------------------------------------------------------------------

def run(root: str | Path = ".") -> int:
    root = Path(root).resolve()
    saved = _existing(root)
    first_run = not saved

    print(f"\n{RULE}")
    print("  SHOW FINDER - SETUP")
    print(RULE)
    print(
        "\nThis asks a few questions about your business so the tool can\n"
        "rank shows using YOUR costs and YOUR prices.\n\n"
        "  * Press ENTER to keep the answer shown in [brackets].\n"
        "  * Nothing is saved until the very end, and you can re-run this\n"
        "    any time from the 'Change My Settings' icon.\n"
        "  * Estimates are fine. You can change any of it later.\n"
    )
    if not first_run:
        print("Your current settings are filled in below.\n")

    try:
        data = _interview(root, saved)
    except Cancelled:
        print("\n\nCancelled - nothing was changed.\n")
        return 1
    return _finish(root, data)


def _interview(root: Path, saved: dict) -> dict:
    data: dict = {"advanced": saved.get("advanced", {})}

    # -- who you are ------------------------------------------------------
    section("1 of 7 - Your business")
    name = ask("What is your business called?",
               _get(saved, "business_name", ""), allow_blank=False)
    data["business_name"] = name

    # -- where you start from --------------------------------------------
    section(
        "2 of 7 - Where you drive from",
        "Every show's distance, fuel cost, and hotel need is measured from\n"
        "here, so get the ZIP code right.",
    )
    city = ask("What city are you based in?", _get(saved, "home.city", ""),
               allow_blank=False)
    state = ask("What state? (two letters, e.g. OH)",
                _get(saved, "home.state", ""), allow_blank=False).upper()[:2]
    zip_code = ask("What is your ZIP code?", str(_get(saved, "home.zip", "")),
                   allow_blank=False)

    lat, lon = _locate(root, city, state, zip_code,
                       _get(saved, "home.lat", None),
                       _get(saved, "home.lon", None))
    data["home"] = {"name": f"{city}, {state}", "city": city, "state": state,
                    "zip": zip_code, "lat": lat, "lon": lon}

    # -- how far you will go ---------------------------------------------
    section(
        "3 of 7 - How far you will travel",
        "Shows farther than this are ignored completely. Driving more than\n"
        "2.5 hours adds a hotel night to the cost of a show.",
    )
    hours = ask_number("Longest one-way drive you'd make, in hours?",
                       float(_get(saved, "max_drive_hours",
                                  config.MAX_DRIVE_HOURS)),
                       minimum=0.5, maximum=24)
    data["max_drive_hours"] = hours

    suggested = business.states_within(lat, lon, hours, home_state=state)
    pretty = ", ".join(s.replace("-", " ") for s in suggested)
    print(f"\nStates within {hours:g} hours of {city}, {state}:\n  {pretty}\n")
    if ask_yes_no("Search all of those?", True):
        data["states"] = suggested
    else:
        typed = ask("Type the states to search, separated by commas",
                    ", ".join(s.replace("-", " ") for s in
                              _get(saved, "states", suggested)))
        chosen = [s.strip().replace(" ", "-") for s in typed.split(",")
                  if s.strip()]
        data["states"] = chosen or suggested

    # -- what you sell ----------------------------------------------------
    section(
        "4 of 7 - What you sell",
        "This is how the tool estimates whether a show makes money.\n"
        "Give it your normal retail prices - round numbers are fine.",
    )
    unit_name = ask("What do you call one item? (jar, candle, shirt, bag)",
                    str(_get(saved, "product.unit_name", "item")),
                    allow_blank=False).lower()
    unit_price = ask_number(f"What does ONE {unit_name} sell for?",
                            float(_get(saved, "product.unit_price", 10.0)),
                            minimum=0.01)
    unit_cost = ask_number(
        f"What does it cost YOU to make/buy one {unit_name}?",
        float(_get(saved, "product.unit_cost", round(unit_price * 0.35, 2))),
        minimum=0.0, maximum=unit_price * 10)
    if unit_cost >= unit_price:
        print("\n  NOTE: your cost is at or above your price, so every sale\n"
              "  loses money and no show will look profitable. Double-check\n"
              "  those two numbers if that isn't right.\n")

    product = {"unit_name": unit_name, "unit_price": unit_price,
               "unit_cost": unit_cost}

    print()
    has_deal = ask_yes_no(
        "Do most customers buy a multi-item deal (like 3 for $25)?",
        bool(_get(saved, "product.deal_units", 0)))
    if has_deal:
        product["deal_units"] = int(ask_number(
            f"How many {unit_name}s in that deal?",
            float(_get(saved, "product.deal_units", 3)),
            minimum=1, maximum=100, integer=True))
        product["deal_price"] = ask_number(
            "What does that deal sell for?",
            float(_get(saved, "product.deal_price",
                       round(unit_price * product["deal_units"] * 0.85, 2))),
            minimum=0.01)
    else:
        product["deal_units"] = 1
        product["deal_price"] = unit_price

    print()
    has_addon = ask_yes_no(
        "Do you sell a cheap add-on at the booth (chips, a drink, a sample)?",
        float(_get(saved, "product.addon_price", 0)) > 0)
    if has_addon:
        addon_name = ask("What is it?",
                         str(_get(saved, "product.addon_name", "add-on")))
        product["addon_name"] = addon_name
        product["addon_price"] = ask_number(
            f"What does one {addon_name} sell for?",
            float(_get(saved, "product.addon_price", 3.0)), minimum=0.0)
        product["addon_cost"] = ask_number(
            f"What does one {addon_name} cost you?",
            float(_get(saved, "product.addon_cost", 1.0)), minimum=0.0)
        share = ask_number(
            "Out of every 100 customers, how many also buy one?",
            float(_get(saved, "product.addon_attach_rate", 0.125)) * 100,
            minimum=0, maximum=100)
        product["addon_attach_rate"] = round(share / 100, 4)
        product["deal_includes_addon"] = ask_yes_no(
            f"Does the deal already include a free {addon_name}?",
            bool(_get(saved, "product.deal_includes_addon", False)))
    else:
        product.update(addon_price=0.0, addon_cost=0.0, addon_attach_rate=0.0,
                       deal_includes_addon=False)
    data["product"] = product

    # -- what the road costs ----------------------------------------------
    section("5 of 7 - What travel costs you",
            "Used to work out fuel, hotel, and food for each show.")
    travel = {
        "mpg": ask_number(
            "Miles per gallon your loaded vehicle gets?",
            float(_get(saved, "travel.mpg", config.MPG)),
            minimum=1, maximum=100),
        "gas_price": ask_number(
            "Price of a gallon of gas, in dollars?",
            float(_get(saved, "travel.gas_price", config.GAS_PRICE)),
            minimum=0.5, maximum=25),
        "lodging_per_night": ask_number(
            "What do you pay for a hotel room per night?",
            float(_get(saved, "travel.lodging_per_night",
                       config.LODGING_PER_NIGHT)),
            minimum=0, maximum=2000),
        "meals_per_day": ask_number(
            "What do you spend on food per day on the road?",
            float(_get(saved, "travel.meals_per_day", config.MEALS_PER_DAY)),
            minimum=0, maximum=1000),
    }
    travel["max_daytrip_hours"] = ask_number(
        "How long a drive will you do there-and-back in one day, without\n"
        "staying over? (longer drives add a hotel night to the cost)",
        float(_get(saved, "travel.max_daytrip_hours", config.MAX_DAYTRIP_HOURS)),
        minimum=0, maximum=12)
    data["travel"] = travel

    # -- how far ahead to plan ---------------------------------------------
    section(
        "6 of 7 - How far ahead you book",
        "Most promoters take applications months in advance, so this is\n"
        "usually longer than you would think.",
    )
    data["planning"] = {
        "months_ahead": int(ask_number(
            "How many months ahead should it plan?",
            float(_get(saved, "planning.months_ahead", config.BEST_MONTHS_AHEAD)),
            minimum=1, maximum=24, integer=True)),
        "top_per_weekend": int(ask_number(
            "How many shows do you want to choose between each weekend?",
            float(_get(saved, "planning.top_per_weekend",
                       config.BEST_TOP_PER_WEEKEND)),
            minimum=1, maximum=50, integer=True)),
        "parallel_fetches": int(_get(saved, "planning.parallel_fetches",
                                     config.DEFAULT_JOBS)),
    }

    # -- logins and application details ------------------------------------
    section(
        "7 of 7 - FestivalNet login and your application details",
        "A FestivalNet Pro account is optional but makes a big difference:\n"
        "with one, the tool reads real booth fees, application deadlines,\n"
        "and promoter emails instead of estimating them.",
    )
    data["_env"] = _ask_credentials(root)
    data["_profile"] = _ask_profile(root, name, data["home"], product)
    return data


def _locate(root: Path, city: str, state: str, zip_code: str,
            old_lat, old_lon) -> tuple[float, float]:
    """Turn the home town into coordinates, without making it the user's problem."""
    print("\nLooking up that location...", flush=True)
    try:
        from .geocode import Geocoder
        geo = Geocoder(root / "data" / "geocode_cache.json")
        lat, lon, approximate = geo.locate(city, state, zip_code)
        geo.flush()
    except Exception as exc:                      # network down, bad ZIP, ...
        print(f"  Couldn't reach the map service ({exc.__class__.__name__}).")
        lat = lon = None
        approximate = True

    if lat is None or approximate:
        if old_lat is not None and old_lon is not None:
            print("  Keeping the location saved last time.\n")
            return float(old_lat), float(old_lon)
        print("  Using the middle of the state instead. Distances will be\n"
              "  rough until you re-run setup with an internet connection.\n")
        if lat is None:
            return config.HOME_LAT, config.HOME_LON
        return float(lat), float(lon)

    print(f"  Found it: {lat:.4f}, {lon:.4f}\n")
    return float(lat), float(lon)


def _ask_credentials(root: Path) -> dict[str, str]:
    env = read_env(root)
    have = env.get(config.ENV_USERNAME)
    if have:
        print(f"Saved FestivalNet login: {have}")
        if not ask_yes_no("Change it?", False):
            return {}
    elif not ask_yes_no("Do you have a FestivalNet Pro account?", False):
        print("\n  No problem - booth fees will be estimated from crowd size.\n")
        return {}

    user = ask("FestivalNet username or email", have or "")
    if not user:
        return {}
    print("\nPassword (what you type stays hidden - that's normal):")
    try:
        password = getpass.getpass("> ").strip()
    except (EOFError, KeyboardInterrupt):
        raise Cancelled from None
    if not password:
        password = env.get(config.ENV_PASSWORD, "")
    return {config.ENV_USERNAME: user, config.ENV_PASSWORD: password}


def _ask_profile(root: Path, business_name: str, home: dict,
                 product: dict) -> dict:
    profile, _ = pdf_fill.load_profile(root)
    if (root / pdf_fill.PROFILE_FILE).exists():
        print("\nYour application details are already saved.")
        if not ask_yes_no("Review them?", False):
            return {}
    else:
        print(
            "\nWhen the tool downloads a vendor application, it fills these\n"
            "in for you. Leave anything blank that doesn't apply.\n"
        )

    def field(key: str, question: str, default: str = "") -> str:
        current = str(profile.get(key, "") or "")
        # Compare against the shipped template rather than guessing at what
        # looks like filler: "YOUR NAME" is obvious, but "00000" and
        # "you@example.com" are placeholders too, and offering those as the
        # suggested answer is how a bogus ZIP ends up on an application.
        if current == str(pdf_fill.DEFAULT_PROFILE.get(key, "")):
            current = ""
        return ask(question, current or default)

    out = {
        "business_name": business_name,
        "contact_name": field("contact_name", "Your full name"),
        "address": field("address", "Street address"),
        "city": field("city", "City", home["city"]),
        "state": field("state", "State (two letters)", home["state"]),
        "zip": field("zip", "ZIP code", str(home["zip"])),
        "phone": field("phone", "Phone number"),
        "email": field("email", "Email address"),
        "website": field("website", "Website (blank if none)"),
        "product_description": field(
            "product_description", "One line describing what you sell",
            f"Handmade {product['unit_name']}s"),
        "category": field("category", "Vendor category promoters would file "
                                      "you under (e.g. packaged food, craft)"),
        "booth_size": field("booth_size", "Booth size you request", "10x10"),
        "electric_needed": "Yes" if ask_yes_no(
            "Do you need electricity at your booth?",
            str(profile.get("electric_needed", "No")).lower().startswith("y"),
        ) else "No",
        "years_in_business": field("years_in_business", "Years in business"),
        "tax_id": field("tax_id", "Tax ID / EIN (blank to leave off forms)"),
        "vendors_license": field("vendors_license",
                                 "Vendor's license number (blank if none)"),
        "insurance_carrier": field("insurance_carrier",
                                   "Insurance carrier (blank if none)"),
        "signature_date": "",
    }
    return out


# ---------------------------------------------------------------------------
# Saving
# ---------------------------------------------------------------------------

def _finish(root: Path, data: dict) -> int:
    env_updates = data.pop("_env", {}) or {}
    profile = data.pop("_profile", {}) or {}

    section("Here's what will be saved")
    home = data["home"]
    product = data["product"]
    print(f"  Business        {data['business_name']}")
    print(f"  Home base       {home['city']}, {home['state']} {home['zip']}")
    print(f"  Travel limit    {data['max_drive_hours']:g} hours each way")
    print(f"  States searched {len(data['states'])}")
    print(f"  Price           ${product['unit_price']:,.2f} per "
          f"{product['unit_name']}, costs you ${product['unit_cost']:,.2f}")
    if product.get("deal_units", 1) > 1:
        print(f"  Usual sale      {product['deal_units']} for "
              f"${product['deal_price']:,.2f}")
    print(f"  Vehicle         {data['travel']['mpg']:g} mpg at "
          f"${data['travel']['gas_price']:,.2f}/gal")
    print(f"  Hotel needed    over {data['travel']['max_daytrip_hours']:g} "
          f"hours each way, at ${data['travel']['lodging_per_night']:,.0f}/night")
    print(f"  Plans           {data['planning']['months_ahead']} months ahead, "
          f"{data['planning']['top_per_weekend']} shows a weekend")
    # Read the file as well as the answers: keeping an existing login is
    # the common case, and it must not be summarised as "no login".
    login = (env_updates.get(config.ENV_USERNAME)
             or read_env(root).get(config.ENV_USERNAME))
    print(f"  FestivalNet     "
          f"{'logging in as ' + login if login else 'no login (fees estimated)'}")
    print()

    if not ask_yes_no("Save these settings?", True):
        print("\nNothing was saved. Run setup again whenever you're ready.\n")
        return 1

    path = business.save(data, root)
    written = [path]
    if env_updates:
        written.append(write_env(root, env_updates))
    if profile:
        profile_path = root / pdf_fill.PROFILE_FILE
        profile_path.write_text(json.dumps(profile, indent=2) + "\n",
                                encoding="utf-8")
        written.append(profile_path)
    pdf_fill.write_example_profile(root)

    # Make the new numbers live for anything that runs in this process.
    config.reload_business(data)

    print(f"\n{RULE}")
    print("  SAVED - you're ready to go")
    print(RULE)
    for p in written:
        print(f"  {p.name}")
    print(
        "\nNext: close this window and double-click\n"
        '  "1 - Find My Shows"\n\n'
        "The first search takes 45-75 minutes because it reads a few\n"
        "thousand event listings. Leave the window open; it prints what\n"
        "it's doing as it goes. After that, results come back in seconds.\n"
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:]) if argv is None else list(argv)
    root = argv[0] if argv and not argv[0].startswith("-") else "."
    return run(root)


if __name__ == "__main__":                          # pragma: no cover
    raise SystemExit(main())

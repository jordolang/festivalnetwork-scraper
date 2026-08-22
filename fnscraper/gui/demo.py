"""A synthetic result set, so the window has something to show.

A real crawl takes minutes, and real booth fees need a FestivalNet Pro
login.  This builds a plausible set of listings and runs them through the
*real* scoring model, so every number on screen is one the app actually
computes — only the listings themselves are invented.  The window labels
the session SAMPLE DATA whenever this is what is loaded, and the demo set
is never written to the results file a crawl would use.
"""

from __future__ import annotations

from datetime import date, timedelta

from ..geocode import drive_estimate
from ..models import Event, ScoredEvent
from ..scoring import score_event

# Real coordinates, so the drive times and trip costs are honest even
# though the shows are not.
CITIES: dict[str, tuple[str, float, float]] = {
    "Columbus": ("OH", 39.9612, -82.9988),
    "Cleveland": ("OH", 41.4993, -81.6944),
    "Cincinnati": ("OH", 39.1031, -84.5120),
    "Dayton": ("OH", 39.7589, -84.1916),
    "Athens": ("OH", 39.3292, -82.1013),
    "Marietta": ("OH", 39.4150, -81.4549),
    "Wooster": ("OH", 40.8051, -81.9351),
    "Yellow Springs": ("OH", 39.8059, -83.8880),
    "Toledo": ("OH", 41.6528, -83.5379),
    "Pittsburgh": ("PA", 40.4406, -79.9959),
    "Lancaster": ("PA", 40.0379, -76.3055),
    "Erie": ("PA", 42.1292, -80.0851),
    "Morgantown": ("WV", 39.6295, -79.9559),
    "Charleston": ("WV", 38.3498, -81.6326),
    "Louisville": ("KY", 38.2527, -85.7585),
    "Lexington": ("KY", 38.0406, -84.5037),
    "Indianapolis": ("IN", 39.7684, -86.1581),
    "Bloomington": ("IN", 39.1653, -86.5264),
    "Ann Arbor": ("MI", 42.2808, -83.7430),
    "Grand Rapids": ("MI", 42.9634, -85.6681),
    "Nashville": ("TN", 36.1627, -86.7816),
    "Knoxville": ("TN", 35.9606, -83.9207),
    "Asheville": ("NC", 35.5951, -82.5515),
    "Richmond": ("VA", 37.5407, -77.4360),
    "Roanoke": ("VA", 37.2710, -79.9414),
    "Buffalo": ("NY", 42.8864, -78.8784),
    "Baltimore": ("MD", 39.2904, -76.6122),
    "Milwaukee": ("WI", 43.0389, -87.9065),
}

# name, slug, city, start offset (days), run length, attendance, exhibitors,
# food booths, admission, juried
LISTINGS: tuple[tuple, ...] = (
    ("Riverbend Arts & Crafts Festival", "Art-Shows", "Columbus", 21, 3, 48_000, 210, 24, "Free", "Yes"),
    ("Lakeside Harvest Market", "Farmers-Markets", "Cleveland", 14, 2, 12_500, 90, 12, "Free", "No"),
    ("Queen City Food & Wine Fest", "Food-Festivals", "Cincinnati", 35, 3, 62_000, 180, 65, "$15", "Yes"),
    ("Gem City Maker Market", "Craft-Shows", "Dayton", 28, 2, 9_800, 120, 10, "Free", "Yes"),
    ("Hocking Hills Autumn Craft Show", "Craft-Shows", "Athens", 42, 2, 7_200, 85, 8, "$5", "Yes"),
    ("Ohio River Sternwheel Festival", "Festivals", "Marietta", 49, 3, 34_000, 140, 30, "Free", "No"),
    ("Wayne County Country Fair", "Fairs", "Wooster", 56, 6, 88_000, 260, 55, "$10", "No"),
    ("Yellow Springs Street Fair", "Festivals", "Yellow Springs", 18, 1, 26_000, 250, 22, "Free", "Yes"),
    ("Glass City Holiday Boutique", "Holiday-Shows", "Toledo", 120, 2, 11_400, 130, 6, "$8", "Yes"),
    ("Three Rivers Arts Festival", "Art-Shows", "Pittsburgh", 63, 4, 145_000, 360, 70, "Free", "Yes"),
    ("Steel City Winter Market", "Holiday-Shows", "Pittsburgh", 126, 3, 22_000, 165, 18, "$6", "Yes"),
    ("Lancaster Heritage Craft Days", "Craft-Shows", "Lancaster", 77, 3, 31_000, 220, 20, "$9", "Yes"),
    ("Presque Isle Summer Fest", "Festivals", "Erie", 70, 2, 18_600, 95, 26, "Free", "No"),
    ("Mountaineer Food Truck Round-Up", "Food-Festivals", "Morgantown", 24, 2, 15_800, 70, 48, "Free", "No"),
    ("Capitol Market Fall Festival", "Farmers-Markets", "Charleston", 45, 2, 9_100, 65, 14, "Free", "No"),
    ("Bourbon City Harvest Fair", "Fairs", "Louisville", 84, 4, 96_000, 240, 60, "$12", "No"),
    ("Bluegrass Artisan Market", "Craft-Shows", "Lexington", 31, 2, 13_700, 145, 12, "Free", "Yes"),
    ("Circle City Craft Expo", "Craft-Shows", "Indianapolis", 38, 3, 41_000, 310, 25, "$10", "Yes"),
    ("Limestone Arts Fair", "Art-Shows", "Bloomington", 91, 2, 16_500, 135, 15, "Free", "Yes"),
    ("Ann Arbor Summer Art Fair", "Art-Shows", "Ann Arbor", 98, 4, 210_000, 420, 85, "Free", "Yes"),
    ("Grand River Salsa & Sauce Festival", "Food-Festivals", "Grand Rapids", 105, 2, 27_500, 110, 44, "$7", "No"),
    ("Music City Makers Market", "Craft-Shows", "Nashville", 112, 2, 33_000, 195, 28, "$5", "Yes"),
    ("Smoky Mountain Craft Weekend", "Craft-Shows", "Knoxville", 59, 3, 24_800, 180, 19, "$8", "Yes"),
    ("Blue Ridge Food Truck Rally", "Food-Festivals", "Asheville", 66, 2, 21_400, 60, 52, "Free", "No"),
    ("James River Artisan Festival", "Art-Shows", "Richmond", 74, 3, 38_000, 240, 32, "$6", "Yes"),
    ("Star City Holiday Market", "Holiday-Shows", "Roanoke", 133, 2, 14_200, 120, 11, "$5", "Yes"),
    ("Queen City Winterfest", "Festivals", "Buffalo", 140, 3, 29_000, 150, 34, "Free", "No"),
    ("Inner Harbor Taste Festival", "Food-Festivals", "Baltimore", 88, 2, 55_000, 130, 78, "$18", "No"),
    ("Lakefront Craft Bazaar", "Craft-Shows", "Milwaukee", 95, 2, 19_600, 175, 16, "Free", "Yes"),
    ("Buckeye Country Christmas Show", "Holiday-Shows", "Columbus", 147, 3, 45_000, 330, 22, "$12", "Yes"),
    ("Short North Night Market", "Festivals", "Columbus", 10, 1, 8_400, 70, 20, "Free", "No"),
    ("Flats East Bank Street Feast", "Food-Festivals", "Cleveland", 52, 2, 17_300, 55, 40, "Free", "No"),
    ("Miami Valley Home & Garden Expo", "Home-Garden-Shows", "Dayton", 154, 3, 36_000, 290, 14, "$11", "No"),
    ("Ohio Valley Autumn Fest", "Festivals", "Marietta", 40, 2, 12_900, 100, 18, "Free", "No"),
    ("Blue Grass Bourbon & Bites", "Food-Festivals", "Lexington", 119, 2, 23_700, 80, 46, "$20", "No"),
    ("Steel Valley Farmers Market Day", "Farmers-Markets", "Pittsburgh", 12, 1, 6_300, 55, 9, "Free", "No"),
)

PROMOTERS = (
    "Buckeye Event Group", "Riverfront Promotions", "Heartland Fairs LLC",
    "Main Street Association", "Great Lakes Event Co.", "Valley Arts Council",
)


def _event(index: int, listing: tuple, today: date) -> Event:
    (name, slug, city, offset, length, attendance,
     exhibitors, food_booths, admission, juried) = listing
    state, lat, lon = CITIES[city]
    start = today + timedelta(days=offset)
    end = start + timedelta(days=length - 1)
    miles, hours = drive_estimate(lat, lon)
    promoter = PROMOTERS[index % len(PROMOTERS)]
    deadline = start - timedelta(days=45)
    return Event(
        event_id=f"demo-{index:03d}",
        name=name,
        url=f"https://festivalnet.com/{slug}/{city.replace(' ', '-')}/demo-{index:03d}",
        category_slug=slug,
        start_date=start,
        end_date=end,
        hours_text="Sat 10am-6pm; Sun 11am-5pm" if length <= 3 else "",
        city=city,
        state=state,
        venue=f"{city} {'Fairgrounds' if 'Fair' in name else 'Downtown'}",
        address=f"{100 + index * 7} Main St, {city}, {state}",
        lat=lat,
        lon=lon,
        admission=admission,
        attendance=attendance,
        exhibitors=exhibitors,
        food_booths=food_booths,
        juried=juried,
        deadlines=f"Application deadline {deadline:%m/%d/%Y}",
        promoter=promoter,
        description=(
            f"{name} is a {length}-day event in {city}, {state} drawing about "
            f"{attendance:,} visitors and roughly {exhibitors} exhibitors. "
            "Vendor spaces are 10x10 with electric available on request."
        ),
        contact_name=f"{promoter} — Vendor Coordinator",
        contact_email=f"vendors@{promoter.split()[0].lower()}.example",
        contact_phone=f"(740) 555-{1000 + index:04d}",
        distance_miles=miles,
        drive_hours=hours,
    )


def sample_results(today: date | None = None) -> list[ScoredEvent]:
    """Score the invented listings with the shipped model."""
    today = today or date.today()
    scored = [score_event(_event(i, listing, today))
              for i, listing in enumerate(LISTINGS)]
    scored.sort(key=lambda s: s.breakdown.score, reverse=True)
    return scored

"""Fixture keys and expected results for the canonical world (docs/architecture/fixtures.md).

Integrator-owned (steward: tasks/briefings lane). Tests, seeds and e2e reference these constants,
never literal names, numbers or sentences. ``SeedContext.refs`` maps each key (e.g. ``"MEERA"``)
to the id the seed created; business numbers below follow from creation order through the real
allocator (fixtures.md §1 rule 4).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

# ---- clock -----------------------------------------------------------------------------------
#: D0 — Monday 2026-10-12 08:55 IST
CLOCK_D0 = datetime(2026, 10, 12, 3, 25, tzinfo=UTC)
ZONE = "Asia/Kolkata"

# ---- company, branches, teams, calendar ------------------------------------------------------
COMPANY_KEY = "crown-demo"
COMPANY_LEGAL_NAME = "Crown Decor Pvt. Ltd. (Demo)"
COMPANY_DISPLAY_NAME = "Crown Decor (Demo)"
BRANDS = SimpleNamespace(LK="LK", CR="CR")
#: display names of the brands (the org ``brands`` setting defaults)
BRAND_NAMES = {BRANDS.LK: "Lamikraft", BRANDS.CR: "Crown"}
BRANCHES = SimpleNamespace(HO="HO", FAC="FAC")
TEAMS = SimpleNamespace(EXP_SALES="EXP-SALES", OPS_HO="OPS-HO")
CALENDARS = SimpleNamespace(HO_GEN="HO-GEN")
SHIFTS = SimpleNamespace(GEN="GEN", NGT="NGT")
#: (start, end, rollover, precompute minutes before shift start) for HO-GEN / shift GEN
CALENDAR_HO_GEN_WINDOW = ("09:30", "18:30", "04:00", 30)
#: (name, offset in days from D0)
HOLIDAYS = SimpleNamespace(DEMO=("Demo holiday", 10))
CURRENCIES = ("INR", "EUR", "USD", "GBP")
EMAIL_DOMAIN = "demo.lamikraft.test"


@dataclass(frozen=True)
class Person:
    key: str
    name: str
    email: str
    role_template: str
    scope: str  # own | team | branch | company (headline scope of the role template)
    branch: str
    team: str | None
    manager: str | None
    slice_no: int = 1


def _p(key: str, name: str, role: str, scope: str, team: str | None, manager: str | None, slice_no: int = 1) -> Person:
    local = name.lower().replace(" ", ".")
    return Person(key, name, f"{local}@{EMAIL_DOMAIN}", role, scope, BRANCHES.HO, team, manager, slice_no)


PEOPLE: dict[str, Person] = {
    p.key: p
    for p in (
        _p("SAHIL", "Sahil Mehta", "management", "company", TEAMS.EXP_SALES, None),
        _p("MEERA", "Meera Iyer", "sales", "own", TEAMS.EXP_SALES, "SAHIL"),
        _p("NEHA", "Neha Joshi", "sales", "own", TEAMS.EXP_SALES, "SAHIL"),
        _p("RAVI", "Ravi Kumar", "operations", "branch", TEAMS.OPS_HO, None),
        _p("KABIR", "Kabir Shah", "warehouse", "own", TEAMS.OPS_HO, "RAVI"),
        _p("ARJUN", "Arjun Das", "sales", "own", TEAMS.EXP_SALES, "SAHIL"),
        _p("ANANYA", "Ananya Rao", "finance", "company", None, None),
        _p("PRIYA", "Priya Nair", "admin", "company", None, None),
        _p("VIKRAM", "Vikram Singh", "operations", "branch", TEAMS.OPS_HO, "RAVI", slice_no=2),
    )
}
USERS = SimpleNamespace(**{k: k for k in PEOPLE})
#: team leads (fixtures.md §2)
TEAM_LEADS = {TEAMS.EXP_SALES: "SAHIL", TEAMS.OPS_HO: "RAVI"}

# ---- parties ---------------------------------------------------------------------------------
PARTIES = SimpleNamespace(
    NORDHAUS="P-00001",
    MAISON="P-00002",
    BERG="P-00003",
    THORNBURY="P-00004",
    KAVERI="P-00005",  # slice 2
    PRECISION_EDGE="P-00006",  # slice 2
)
PARTY_NAMES = {
    "NORDHAUS": "Nordhaus Interiors GmbH",
    "MAISON": "Maison Atelier SARL",
    "BERG": "Berg & Co AB",
    "THORNBURY": "Thornbury Kitchens Ltd",
    "KAVERI": "Kaveri Timber Supplies",
    "PRECISION_EDGE": "Precision Edge Fabricators",
}

#: SeedContext.refs keys of the parties (the attribute names of PARTIES)
PARTY_REFS = SimpleNamespace(**{k: k for k in PARTY_NAMES})
#: (name, email) of each customer's primary contact; fictional ``.test`` addresses
CONTACTS = {
    "NORDHAUS": ("Lena Brandt", "lena.brandt@nordhaus-interiors.test"),
    "MAISON": ("Camille Laurent", "camille.laurent@maison-atelier.test"),
    "BERG": ("Erik Lindqvist", "erik.lindqvist@bergco.test"),
    "THORNBURY": ("Oliver Hart", "oliver.hart@thornbury-kitchens.test"),
}

# ---- catalogue -------------------------------------------------------------------------------
#: SeedContext.refs keys of the taxonomy rows, and their names (fixtures.md §5)
CATEGORIES = SimpleNamespace(SERVEWARE="CAT_SERVEWARE", DECORATIVE_BOARDS="CAT_DECORATIVE_BOARDS")
SUBCATEGORIES = SimpleNamespace(
    TRAYS="SUB_TRAYS", TRIVETS="SUB_TRIVETS", BOARDS="SUB_BOARDS", VENEERED_PANELS="SUB_VENEERED_PANELS"
)
TAXONOMY_NAMES = {
    CATEGORIES.SERVEWARE: "Serveware",
    CATEGORIES.DECORATIVE_BOARDS: "Decorative Boards",
    SUBCATEGORIES.TRAYS: "Trays",
    SUBCATEGORIES.TRIVETS: "Trivets",
    SUBCATEGORIES.BOARDS: "Boards",
    SUBCATEGORIES.VENEERED_PANELS: "Veneered panels",
}
PRODUCTS = SimpleNamespace(
    OAK_TRAY="LK-OT-0450",
    MAPLE_TRIVET="LK-MT-0300",
    ASH_BOARD="LK-AB-0400",
    WALNUT_BOARD="LK-WB-1800",
)
OAK_TRAY_VARIANTS = ("LK-OT-0300", "LK-OT-0600", "LK-OT-0750", "LK-OT-0900")  # slice 2
DECORS = SimpleNamespace(NATURAL_OAK="0120", HARD_MAPLE="0310", WHITE_ASH="0415", AMERICAN_WALNUT="0457")
#: product names keyed by the PRODUCTS attribute (also the SeedContext.refs key of the product)
PRODUCT_NAMES = {
    "OAK_TRAY": "Oak serving tray 450",
    "MAPLE_TRIVET": "Maple trivet 300",
    "ASH_BOARD": "Ash chopping board 400",
    "WALNUT_BOARD": "Walnut veneered board 18 mm",
}
DECOR_NAMES = {
    DECORS.NATURAL_OAK: "Natural Oak",
    DECORS.HARD_MAPLE: "Hard Maple",
    DECORS.WHITE_ASH: "White Ash",
    DECORS.AMERICAN_WALNUT: "American Walnut",
}

# ---- pricing ---------------------------------------------------------------------------------
PRICE_LISTS = SimpleNamespace(EXP_EUR="EXP-EUR-2026", EXP_GBP="EXP-GBP-2026", DOM_INR="DOM-INR-2026")
#: SeedContext.refs keys of the price lists and their items (fixtures.md §6 "Key" column)
PRICE_LIST_REFS = SimpleNamespace(EXP_EUR="PL_EXP_EUR", EXP_GBP="PL_EXP_GBP", DOM_INR="PL_DOM_INR")
PRICE_LIST_NAMES = {"EXP_EUR": "Export EUR 2026", "EXP_GBP": "Export GBP 2026", "DOM_INR": "Domestic INR 2026"}
PRICE_LIST_ITEM_REFS = SimpleNamespace(
    EXP_EUR_OAK_TRAY="PLI_EXP_EUR_OAK_TRAY",
    EXP_EUR_MAPLE_TRIVET="PLI_EXP_EUR_MAPLE_TRIVET",
    EXP_EUR_ASH_BOARD="PLI_EXP_EUR_ASH_BOARD",
    EXP_GBP_OAK_TRAY="PLI_EXP_GBP_OAK_TRAY",
    DOM_INR_WALNUT_BOARD="PLI_DOM_INR_WALNUT_BOARD",
)
PRICES = SimpleNamespace(OAK_TRAY_EUR="24.0000", OAK_TRAY_GBP="21.0000", MAPLE_TRIVET_EUR="9.5000",
                         ASH_BOARD_EUR="18.0000", WALNUT_BOARD_INR="3450.0000")
COMMERCIAL = SimpleNamespace(RULE_SET="quote_commercial", EUR_MINIMUM="5000.00", SURCHARGE="400.00")
#: SeedContext.refs key of the commercial rule set
RULE_SET_REFS = SimpleNamespace(QUOTE_COMMERCIAL="RULE_SET_QUOTE_COMMERCIAL")

# ---- sales -----------------------------------------------------------------------------------
ENQUIRIES = SimpleNamespace(MAISON="ENQ-2026-0001", THORNBURY="ENQ-2026-0002")
MESSAGES = SimpleNamespace(NORDHAUS="MSG_NORDHAUS", BERG="MSG_BERG")
QUOTES = SimpleNamespace(
    BERG_WON="LK-QT-2026-0001",
    THORNBURY_LOST="LK-QT-2026-0002",
    PRIOR_WON="LK-QT-2026-0003",
    THORNBURY_EXPIRING="LK-QT-2026-0004",
    MAISON_OVERRIDE="LK-QT-2026-0005",
    BERG_EXPIRING="LK-QT-2026-0006",
    THORNBURY_OVERRIDE="LK-QT-2026-0007",
    NORDHAUS_DRAFT="LK-QT-2026-0008",
    SCENARIO_C_NEW="LK-QT-2026-0009",  # created by scenario C at D0
)
PROPOSALS = SimpleNamespace(MAISON="PROP_MAISON", THORNBURY="PROP_THORNBURY", NORDHAUS="PROP_NORDHAUS")
#: SeedContext.refs keys of the quotes and enquiries (QUOTES and ENQUIRIES hold their business numbers)
QUOTE_REFS = SimpleNamespace(**{k: f"Q_{k}" for k in vars(QUOTES)})
ENQUIRY_REFS = SimpleNamespace(**{k: f"ENQ_{k}" for k in vars(ENQUIRIES)})

# ---- delivery challans (Slice 2; fixtures.md §8) ---------------------------------------------
#: business numbers follow from creation order through the yearly ``DC`` allocator
CHALLANS = SimpleNamespace(
    JOB_WORK="DC-2026-0001",  # Job Work, returnable, to Precision Edge Fabricators; issued D-7 by Ravi, expected return D0+1
    SAMPLE_MAISON="DC-2026-0002",  # Sample, returnable, to Maison; issued D-3 by Ravi
    OUTWARD_DRAFT="DC-2026-0003",  # Outward, non-returnable, to Nordhaus; Ravi's draft at D0 08:30
)
#: SeedContext.refs keys of the challans ("DC_" + CHALLANS attribute)
CHALLAN_REFS = SimpleNamespace(**{k: f"DC_{k}" for k in vars(CHALLANS)})
#: (product key attribute, quantity) of each fixture challan's single line
CHALLAN_LINES = {
    "JOB_WORK": ("WALNUT_BOARD", "12"),
    "SAMPLE_MAISON": ("ASH_BOARD", "2"),
    "OUTWARD_DRAFT": ("OAK_TRAY", "40"),
}

# ---- tasks and reminders ---------------------------------------------------------------------
TASKS = SimpleNamespace(KABIR_COUNT="TASK_KABIR_COUNT", ARJUN_WALKTHROUGH="TASK_ARJUN_WALKTHROUGH")
REMINDERS = SimpleNamespace(MEERA="REMINDER_MEERA")
#: reminder text and task titles of fixtures.md §7.5
TEXTS = SimpleNamespace(
    REMINDER_MEERA="Call Maison about finish preferences",
    TASK_KABIR_COUNT="Count walnut boards in bin A-12",
    TASK_ARJUN_WALKTHROUGH="Complete product catalogue walkthrough",
)
#: the sales onboarding template's step keys, in order, and their titles
ONBOARDING_STEPS = ("language_and_detail", "open_product", "global_search")
ONBOARDING_STEP_TITLES = {
    "language_and_detail": "Choose your language and briefing detail",
    "open_product": "Open a product record",
    "global_search": "Use global search",
}

# ---- fixture times (local Asia/Kolkata; D0 = Mon 2026-10-12) ---------------------------------
_IST = ZoneInfo(ZONE)
TIMES = SimpleNamespace(
    REMINDER_MEERA_CREATED_AT=datetime(2026, 10, 10, 17, 30, tzinfo=_IST),  # D-2 17:30
    REMINDER_MEERA_AT=datetime(2026, 10, 13, 10, 0, tzinfo=_IST),  # D0+1 10:00
    MEERA_LAST_ACK_AT=datetime(2026, 10, 10, 18, 5, tzinfo=_IST),  # Sat D-2 18:05
    NEHA_BRIEFING_AT=datetime(2026, 10, 12, 8, 49, tzinfo=_IST),  # D0 08:49
    NEHA_ACK_AT=datetime(2026, 10, 12, 8, 50, tzinfo=_IST),  # D0 08:50
    ARJUN_ACTIVATED_AT=datetime(2026, 10, 12, 8, 0, tzinfo=_IST),  # D0 08:00
    TASK_ARJUN_WALKTHROUGH_CREATED_AT=datetime(2026, 10, 12, 8, 5, tzinfo=_IST),  # D0 08:05
    TASK_ARJUN_WALKTHROUGH_DUE_AT=datetime(2026, 10, 14, 18, 30, tzinfo=_IST),  # D0+2 18:30
    TASK_KABIR_COUNT_CREATED_AT=datetime(2026, 10, 12, 8, 10, tzinfo=_IST),  # D0 08:10
    TASK_KABIR_COUNT_DUE_AT=datetime(2026, 10, 12, 14, 0, tzinfo=_IST),  # D0 14:00
)

# ---- expected Slice-1 briefing results (fixtures.md §9) ---------------------------------------
EXPECTED = SimpleNamespace(
    #: issue keys of fixtures.md §9.1 in rank order; ``{REF}`` is the SeedContext.refs id of that key
    MEERA_S1_ITEM_ORDER=(
        "msg:{MSG_BERG}",
        "quote:{Q_BERG_EXPIRING}:expiry",
        "msg:{MSG_NORDHAUS}",
        "info:party:{MAISON}",
        "reminder:{REMINDER_MEERA}",
    ),
    #: A-05: the Berg reply (13:00Z) for a Europe/Berlin user
    BERLIN_DUE_LABEL="Today 15:00",
    MEERA_S1_GREETING="Good morning, Meera.",
    MEERA_S1_SENTENCE="Two customer replies need attention and one quote expires today.",
    SAHIL_S1_GREETING="Good morning, Sahil.",
    SAHIL_S1_SENTENCE="Three decisions need you. The rest is moving.",
    SAHIL_A08_SENTENCE="Three decisions need you. One item is overdue.",
    SAHIL_A09_SENTENCE="One decision needs you. The rest is moving.",
    NEHA_S1_SENTENCE="One quote expires today.",
    ARJUN_S1_SENTENCE="Welcome, Arjun. You have three onboarding steps and one assigned task.",
    KABIR_S1_SENTENCE="One task is due today.",
    RAVI_S1_SENTENCE="One task is due today.",
    PRIYA_S1_SENTENCE="Three decisions need you. The rest is moving.",
    ANANYA_S1_SENTENCE="Nothing needs you right now.",
    MEERA_S2_SENTENCE=(
        "Two customer replies need attention, one quote expires today, and yesterday's sample has been delivered."
    ),
    SCENARIO_C_TOTAL="5760.00",
    SCENARIO_C_QTY="240",
    SCENARIO_D_RECOMMENDED_QTY="216",
)

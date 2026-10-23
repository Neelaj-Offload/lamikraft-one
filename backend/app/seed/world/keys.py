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

# ---- clock -----------------------------------------------------------------------------------
#: D0 — Monday 2026-10-12 08:55 IST
CLOCK_D0 = datetime(2026, 10, 12, 3, 25, tzinfo=UTC)
ZONE = "Asia/Kolkata"

# ---- company, branches, teams, calendar ------------------------------------------------------
COMPANY_KEY = "crown-demo"
COMPANY_LEGAL_NAME = "Crown Decor Pvt. Ltd. (Demo)"
COMPANY_DISPLAY_NAME = "Crown Decor (Demo)"
BRANDS = SimpleNamespace(LK="LK", CR="CR")
BRANCHES = SimpleNamespace(HO="HO", FAC="FAC")
TEAMS = SimpleNamespace(EXP_SALES="EXP-SALES", OPS_HO="OPS-HO")
CALENDARS = SimpleNamespace(HO_GEN="HO-GEN")
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

# ---- catalogue -------------------------------------------------------------------------------
PRODUCTS = SimpleNamespace(
    OAK_TRAY="LK-OT-0450",
    MAPLE_TRIVET="LK-MT-0300",
    ASH_BOARD="LK-AB-0400",
    WALNUT_BOARD="LK-WB-1800",
)
OAK_TRAY_VARIANTS = ("LK-OT-0300", "LK-OT-0600", "LK-OT-0750", "LK-OT-0900")  # slice 2
DECORS = SimpleNamespace(NATURAL_OAK="0120", HARD_MAPLE="0310", WHITE_ASH="0415", AMERICAN_WALNUT="0457")

# ---- pricing ---------------------------------------------------------------------------------
PRICE_LISTS = SimpleNamespace(EXP_EUR="EXP-EUR-2026", EXP_GBP="EXP-GBP-2026", DOM_INR="DOM-INR-2026")
PRICES = SimpleNamespace(OAK_TRAY_EUR="24.0000", OAK_TRAY_GBP="21.0000", MAPLE_TRIVET_EUR="9.5000",
                         ASH_BOARD_EUR="18.0000", WALNUT_BOARD_INR="3450.0000")
COMMERCIAL = SimpleNamespace(RULE_SET="quote_commercial", EUR_MINIMUM="5000.00", SURCHARGE="400.00")

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

# ---- tasks and reminders ---------------------------------------------------------------------
TASKS = SimpleNamespace(KABIR_COUNT="TASK_KABIR_COUNT", ARJUN_WALKTHROUGH="TASK_ARJUN_WALKTHROUGH")
REMINDERS = SimpleNamespace(MEERA="REMINDER_MEERA")

# ---- expected Slice-1 briefing results (fixtures.md §9) ---------------------------------------
EXPECTED = SimpleNamespace(
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

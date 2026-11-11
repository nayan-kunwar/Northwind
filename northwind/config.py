from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
OUTPUT = ROOT / "output"

BUNDLE_ID = "NWG-D0BC"
INITIALS = "nk"
PRESENTATION_CURRENCY = "GBP"

ENTITIES = ("US", "UK", "IN")
ENTITY_FILES = {
    "US": "tb_us.csv",
    "UK": "tb_uk.csv",
    "IN": "tb_in.csv",
}
ENTITY_CURRENCY = {"US": "USD", "UK": "GBP", "IN": "INR"}
ENTITY_OWNERSHIP = {"US": None, "UK": Decimal("1.0"), "IN": Decimal("0.8")}

# Policy assumptions, stated in DECISIONS.md.
FY_START = "2024-01-01"
FY_END = "2024-12-31"
INDIA_ACQUISITION = "2024-07-01"
INDIA_NCI_PCT = Decimal("0.20")
INDIA_GOODWILL_INR = 147_600_000
INDIA_NET_ASSETS_ACQ_INR = 678_000_000
INDIA_NCI_ACQ_INR = 135_600_000
INDIA_SHARE_CAPITAL_INR = 250_000_000
INDIA_RESERVES_INR = 410_000_000
INDIA_H1_PROFIT_INR = 18_000_000

# Systematic India P&L accounts: a manual "accrue" for a period already in the
# monthly ledger is treated as a possible duplicate and held.
INDIA_SYSTEMATIC_ACCOUNTS = {"IN-DEP", "IN-FIN"}

# UK subledger reclass: both AR and AP control totals differ by 45,000.
UK_SUBLEDGER_RECLASS = 45_000

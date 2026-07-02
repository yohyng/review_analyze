"""Shared paths and constants."""
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "reviews.db"

APP_VERSION = "0.6.0"

# Facility roles (step 1 / step 2)
FACILITY_TYPES = {
    "target": "対象施設",
    "comparison": "比較施設",
}

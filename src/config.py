"""
Garmin Training Insights - Configuration
Centralized config loaded from .env file.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# Project paths
PROJECT_ROOT = Path(__file__).parent.parent
DATA_DIR = PROJECT_ROOT / "data"
ACTIVITIES_DIR = DATA_DIR / "activities"
DAILY_DIR = DATA_DIR / "daily"
CONSOLIDATED_DIR = DATA_DIR / "consolidated"
TOKENS_DIR = DATA_DIR / "garth_tokens"

# Ensure directories exist
for d in [DATA_DIR, ACTIVITIES_DIR, DAILY_DIR, CONSOLIDATED_DIR, TOKENS_DIR]:
    d.mkdir(parents=True, exist_ok=True)

# Load environment variables
load_dotenv(PROJECT_ROOT / ".env")

# Garmin Connect credentials
GARMIN_EMAIL = os.getenv("GARMIN_EMAIL")
GARMIN_PASSWORD = os.getenv("GARMIN_PASSWORD")

# FTP values (set during onboarding, updated over time)
def _get_ftp(key):
    val = os.getenv(key)
    if val and val.strip():
        try:
            return float(val)
        except ValueError:
            pass
    return None

RUNNING_FTP = _get_ftp("RUNNING_FTP")
CYCLING_FTP = _get_ftp("CYCLING_FTP")

# Analysis settings
ANALYSIS_TIMEZONE = os.getenv("ANALYSIS_TIMEZONE", "Europe/Prague")

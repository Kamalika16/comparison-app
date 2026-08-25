"""
Application configuration / settings.

Values can be overridden via environment variables (see .env.example).
"""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

UPLOAD_DIR = Path(os.getenv("UPLOAD_DIR", BASE_DIR / "uploads"))
OUTPUT_DIR = Path(os.getenv("OUTPUT_DIR", BASE_DIR / "outputs"))

UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# Max upload size per file, in bytes (default 10 MB)
MAX_UPLOAD_SIZE = int(os.getenv("MAX_UPLOAD_SIZE", 10 * 1024 * 1024))

# Allowed file extensions for uploaded spreadsheets
ALLOWED_EXTENSIONS = {".xlsx", ".xls", ".csv"}

# CORS origins allowed to call the API (comma-separated in env)
CORS_ORIGINS = os.getenv("CORS_ORIGINS", "http://localhost:5173").split(",")

# Fuzzy-matching threshold (0-100) used by column_mapper
COLUMN_MATCH_THRESHOLD = int(os.getenv("COLUMN_MATCH_THRESHOLD", 70))

# Hours tolerance (in decimal hours) below which a discrepancy is "minor"
HOURS_TOLERANCE_MINOR = float(os.getenv("HOURS_TOLERANCE_MINOR", 0.25))
HOURS_TOLERANCE_MAJOR = float(os.getenv("HOURS_TOLERANCE_MAJOR", 1.0))

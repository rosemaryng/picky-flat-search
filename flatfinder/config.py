"""Central configuration. Everything is optional — the app runs fully offline
with deterministic fallbacks when keys are absent, so you can demo locally and
drop real keys in at the hackathon."""
import os

# Search defaults (Rightmove region code 87490 = London)
RIGHTMOVE_REGION = os.environ.get("RIGHTMOVE_REGION", "87490")

# External services (all optional)
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")

SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_KEY", "") or os.environ.get("SUPABASE_KEY", "")

PAYPAL_CLIENT_ID = os.environ.get("PAYPAL_CLIENT_ID", "")
PAYPAL_SECRET = os.environ.get("PAYPAL_SECRET", "")
PAYPAL_BASE = os.environ.get("PAYPAL_BASE", "https://api-m.sandbox.paypal.com")

TFL_APP_KEY = os.environ.get("TFL_APP_KEY", "")  # optional, raises rate limits

HTTP_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120 Safari/537.36"
)

# Where local (no-Supabase) state is kept
LOCAL_DB_PATH = os.environ.get("LOCAL_DB_PATH", os.path.join(os.path.dirname(__file__), "..", "local_db.json"))


def has_openai() -> bool:
    return bool(OPENAI_API_KEY)


def has_supabase() -> bool:
    return bool(SUPABASE_URL and SUPABASE_KEY)


def has_paypal() -> bool:
    return bool(PAYPAL_CLIENT_ID and PAYPAL_SECRET)

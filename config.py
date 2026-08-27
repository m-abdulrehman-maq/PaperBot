"""Central configuration read from environment variables."""
import os


def _bool(name, default=False):
    return os.environ.get(name, str(default)).lower() in ("1", "true", "yes")


# Core — Turso (libSQL) database, accessed over its HTTP API.
TURSO_DATABASE_URL = os.environ.get("TURSO_DATABASE_URL", "")
TURSO_AUTH_TOKEN = os.environ.get("TURSO_AUTH_TOKEN", "")
SECRET_KEY = os.environ.get("SECRET_KEY", "change-me-in-production")

# Admin bootstrap (used only to create the first admin if none exists)
ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "")

# AI
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")

# WhatsApp (worker sends async results back to users)
WHATSAPP_TOKEN = os.environ.get("WHATSAPP_TOKEN", "")
PHONE_NUMBER_ID = os.environ.get("PHONE_NUMBER_ID", "")
GRAPH_API_VERSION = os.environ.get("GRAPH_API_VERSION", "v21.0")

# Object storage (DO Spaces / S3-compatible). Optional.
SPACES_KEY = os.environ.get("SPACES_KEY", "")
SPACES_SECRET = os.environ.get("SPACES_SECRET", "")
SPACES_REGION = os.environ.get("SPACES_REGION", "blr1")
SPACES_BUCKET = os.environ.get("SPACES_BUCKET", "")
SPACES_ENDPOINT = os.environ.get(
    "SPACES_ENDPOINT", f"https://{SPACES_REGION}.digitaloceanspaces.com")

# Worker
WORKER_ENABLED = _bool("WORKER_ENABLED", True)
WORKER_POLL_SECONDS = int(os.environ.get("WORKER_POLL_SECONDS", "5"))

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = Path(os.environ.get("MINISUITE_DB", str(ROOT / "minisuite.sqlite")))
DB_URL = f"sqlite:///{DB_PATH}"

_tokens_raw = os.environ.get("MINISUITE_TOKEN", "demo-token-ridgeline")
TOKENS = {t.strip() for t in _tokens_raw.split(",") if t.strip()}
DEV_TOKEN = next(iter(TOKENS))

HOST = os.environ.get("MINISUITE_HOST", "0.0.0.0")
PORT = int(os.environ.get("PORT", os.environ.get("MINISUITE_PORT", "8000")))

SUBSIDIARY_ID = "1"
CURRENCY_ID = "1"

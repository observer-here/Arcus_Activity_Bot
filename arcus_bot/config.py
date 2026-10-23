import logging
import os
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "watches.db"
ENV_PATH = ROOT / ".env"

REST = "https://api.arcus.xyz"
WS = "wss://api.arcus.xyz/v1/ws"
ADDR = re.compile(r"^0x[0-9a-fA-F]{40}$")
MAX_PER_CHAT = 10

log = logging.getLogger("arcus")


def load_env():
    if not ENV_PATH.exists():
        return
    for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))

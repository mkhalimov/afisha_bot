import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")
if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is required in .env")

_channel_raw = os.getenv("CHANNEL_ID", "")
if not _channel_raw:
    raise RuntimeError("CHANNEL_ID is required in .env")
try:
    CHANNEL_ID: int | str = int(_channel_raw)
except ValueError:
    CHANNEL_ID = _channel_raw  # e.g. "@mychannel"

_admin_ids_raw = os.getenv("ADMIN_IDS", "")
if not _admin_ids_raw:
    raise RuntimeError("ADMIN_IDS is required in .env (comma-separated Telegram user IDs)")
try:
    ADMIN_IDS: set[int] = {int(x.strip()) for x in _admin_ids_raw.split(",") if x.strip()}
except ValueError:
    raise RuntimeError("ADMIN_IDS must be comma-separated integers")
if not ADMIN_IDS:
    raise RuntimeError("ADMIN_IDS must contain at least one user ID")

ADMIN_CHAT_ID_RAW = os.getenv("ADMIN_CHAT_ID", "")
if not ADMIN_CHAT_ID_RAW:
    raise RuntimeError("ADMIN_CHAT_ID is required in .env")
try:
    ADMIN_CHAT_ID: int = int(ADMIN_CHAT_ID_RAW)
except ValueError:
    raise RuntimeError("ADMIN_CHAT_ID must be an integer")

DB_PATH: str = os.getenv("DB_PATH", "data/announcements.db")

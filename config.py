import os
from dotenv import load_dotenv

load_dotenv()

API_ID        = int(os.environ["API_ID"])
API_HASH      = os.environ["API_HASH"]
PHONE         = os.environ["PHONE"]
BOT_USERNAME  = os.environ["BOT_USERNAME"]
SESSION_NAME  = os.environ.get("SESSION_NAME", "userbot")
CHANNELS_FILE = os.environ.get("CHANNELS_FILE", "channels.json")

POLL_INTERVAL   = float(os.environ.get("POLL_INTERVAL", "2.0"))
BATCH_SIZE      = int(os.environ.get("BATCH_SIZE", "50"))
BATCH_PAUSE     = float(os.environ.get("BATCH_PAUSE", "0.02"))
ALBUM_WAIT      = float(os.environ.get("ALBUM_WAIT", "0.5"))
SEND_WORKERS    = int(os.environ.get("SEND_WORKERS", "3"))
DEDUP_TTL       = int(os.environ.get("DEDUP_TTL", "300"))
RECONNECT_BASE  = int(os.environ.get("RECONNECT_BASE", "5"))
RECONNECT_MAX   = int(os.environ.get("RECONNECT_MAX", "120"))
RELOAD_INTERVAL = int(os.environ.get("RELOAD_INTERVAL", "60"))

"""Читает channels.json и печатает отсортированный список."""
import json
from config import CHANNELS_FILE

with open(CHANNELS_FILE, "r", encoding="utf-8") as f:
    channels = json.load(f)

channels.sort(key=lambda c: (c.get("title") or "").lower())

print(f"\n{'─'*65}")
print(f"{'#':<5} {'TITLE':<38} {'ID':>14}  USERNAME")
print(f"{'─'*65}")

for i, c in enumerate(channels, 1):
    title    = (c.get("title") or "")[:37]
    cid      = c.get("id", "?")
    username = f"@{c['username']}" if c.get("username") else "—"
    print(f"{i:<5} {title:<38} {cid:>14}  {username}")

print(f"{'─'*65}")
print(f"Total: {len(channels)}\n")

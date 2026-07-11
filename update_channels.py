"""
Добавляет в channels.json новые каналы из диалогов аккаунта.
Запускать вручную когда подписались на новые каналы.
"""
import asyncio
import json
import os

from telethon import TelegramClient
from telethon.tl.types import Channel

from config import API_ID, API_HASH, PHONE, SESSION_NAME, CHANNELS_FILE


async def main() -> None:
    client = TelegramClient(SESSION_NAME, API_ID, API_HASH)
    await client.start(phone=PHONE)

    # load existing
    if os.path.exists(CHANNELS_FILE):
        with open(CHANNELS_FILE, "r", encoding="utf-8") as f:
            saved: list[dict] = json.load(f)
    else:
        saved = []

    saved_ids = {int(c["id"]) for c in saved}

    added = []
    async for dialog in client.iter_dialogs(limit=None):
        entity = dialog.entity
        # только broadcast-каналы (не группы, не боты)
        if not isinstance(entity, Channel) or not entity.broadcast:
            continue
        if entity.id in saved_ids:
            continue

        added.append({
            "id": entity.id,
            "access_hash": entity.access_hash,
            "title": entity.title,
            "username": entity.username or None,
        })
        saved_ids.add(entity.id)

    if added:
        saved.extend(added)
        with open(CHANNELS_FILE, "w", encoding="utf-8") as f:
            json.dump(saved, f, ensure_ascii=False, indent=4)
        print(f"✅ Добавлено {len(added)} каналов:")
        for c in added:
            u = f"@{c['username']}" if c["username"] else "—"
            print(f"   {c['title'][:45]:<45} {u}")
    else:
        print("📂 Новых каналов нет.")

    await client.disconnect()


asyncio.run(main())

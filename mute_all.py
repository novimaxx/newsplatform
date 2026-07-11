"""Отключает уведомления для всех каналов из channels.json."""
import asyncio
import json
from datetime import timedelta

from telethon import TelegramClient
from telethon.tl.functions.account import UpdateNotifySettingsRequest
from telethon.tl.types import InputNotifyPeer, InputPeerNotifySettings, InputChannel
from telethon.errors import FloodWaitError

from config import API_ID, API_HASH, SESSION_NAME, CHANNELS_FILE


async def main():
    client = TelegramClient(SESSION_NAME, API_ID, API_HASH)
    await client.connect()

    if not await client.is_user_authorized():
        print("❌ Не авторизован! Сначала: python3 auth.py")
        return

    with open(CHANNELS_FILE, encoding="utf-8") as f:
        channels = json.load(f)

    print(f"Каналов: {len(channels)}\n")
    ok = fail = 0

    for i, c in enumerate(channels, 1):
        title    = (c.get("title") or "")[:40]
        username = c.get("username")
        cid      = c.get("id")
        ah       = c.get("access_hash")

        try:
            if username:
                peer = await client.get_input_entity(username)
            else:
                peer = InputChannel(int(cid), int(ah))

            await client(UpdateNotifySettingsRequest(
                peer=InputNotifyPeer(peer),
                settings=InputPeerNotifySettings(
                    mute_until=2**31 - 1,  # навсегда
                    silent=True,
                )
            ))
            ok += 1
            print(f"[{i}/{len(channels)}] 🔕 {title}")

        except FloodWaitError as e:
            print(f"[{i}/{len(channels)}] ⏳ FloodWait {e.seconds}s...")
            await asyncio.sleep(e.seconds + 1)

        except Exception as e:
            fail += 1
            print(f"[{i}/{len(channels)}] ❌ {title}: {e}")

        await asyncio.sleep(0.3)

    print(f"\n✅ Готово: {ok}  ❌ Ошибок: {fail}")
    await client.disconnect()


asyncio.run(main())

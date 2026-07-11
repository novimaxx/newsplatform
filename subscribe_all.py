"""
Подписывается на все каналы из channels.json.
Запускать ПОСЛЕ авторизации (python3 auth.py).
"""
import asyncio
import json

from telethon import TelegramClient
from telethon.tl.functions.channels import JoinChannelRequest
from telethon.tl.types import InputChannel
from telethon.errors import FloodWaitError, UserAlreadyParticipantError

from config import API_ID, API_HASH, SESSION_NAME, CHANNELS_FILE

DELAY = 3.0  # секунд между подписками


async def main():
    client = TelegramClient(SESSION_NAME, API_ID, API_HASH)
    await client.connect()

    if not await client.is_user_authorized():
        print("❌ Не авторизован! Сначала запусти: python3 auth.py")
        return

    with open(CHANNELS_FILE, encoding="utf-8") as f:
        channels = json.load(f)

    print(f"Каналов для подписки: {len(channels)}\n")

    ok = 0
    skip = 0
    fail = 0

    for i, c in enumerate(channels, 1):
        title = (c.get("title") or "")[:40]
        cid   = c.get("id")
        ah    = c.get("access_hash")

        if not cid or not ah:
            skip += 1
            continue

        # используем username если есть, иначе InputChannel
        username = c.get("username")
        peer = username if username else InputChannel(int(cid), int(ah))

        try:
            await client(JoinChannelRequest(peer))
            ok += 1
            print(f"[{i}/{len(channels)}] ✅ {title}")

        except UserAlreadyParticipantError:
            ok += 1
            print(f"[{i}/{len(channels)}] ✓  {title} (уже подписан)")

        except FloodWaitError as e:
            print(f"[{i}/{len(channels)}] ⏳ FloodWait {e.seconds}s — жду...")
            await asyncio.sleep(e.seconds + 2)
            try:
                await client(JoinChannelRequest(peer))
                ok += 1
                print(f"[{i}/{len(channels)}] ✅ {title} (повтор)")
            except Exception as e2:
                fail += 1
                print(f"[{i}/{len(channels)}] ❌ {title}: {e2}")

        except Exception as e:
            fail += 1
            print(f"[{i}/{len(channels)}] ❌ {title}: {e}")

        await asyncio.sleep(DELAY)

    print(f"\n✅ Подписан: {ok}  ❌ Ошибок: {fail}  Пропущено: {skip}")
    await client.disconnect()


asyncio.run(main())

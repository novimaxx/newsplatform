import asyncio
import json
import logging
from datetime import datetime

from telethon import TelegramClient, events
from telethon.errors import FloodWaitError

from config import API_ID, API_HASH, BOT_USERNAME, CHANNELS_FILE, SESSION_NAME, ALBUM_WAIT

# подавляем спам про "missing message mappings"
logging.getLogger("telethon").setLevel(logging.ERROR)

# ── logger ────────────────────────────────────────────────────────────────────
def log(level: str, msg: str) -> None:
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] [{level}] {msg}", flush=True)

# ── load channels ─────────────────────────────────────────────────────────────
def load_channels() -> tuple[set[int], dict[int, str]]:
    with open(CHANNELS_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    ids: set[int] = set()
    labels: dict[int, str] = {}
    for c in data:
        cid = c.get("id")
        if not cid:
            continue
        cid = int(cid)
        ids.add(cid)
        labels[cid] = f"@{c['username']}" if c.get("username") else str(cid)
    return ids, labels

ALLOWED_IDS, CHANNEL_LABELS = load_channels()
log("INFO", f"Tracking {len(ALLOWED_IDS)} channels")

# ── album buffers ─────────────────────────────────────────────────────────────
album_buffer: dict[int, list[int]] = {}
album_tasks:  dict[int, asyncio.Task] = {}

# ── forward / copy ────────────────────────────────────────────────────────────
async def mark_read(client, peer, max_id: int) -> None:
    try:
        await client.send_read_acknowledge(peer, max_id=max_id)
    except Exception:
        pass


async def safe_forward(client, peer, message_ids) -> None:
    ids = message_ids if isinstance(message_ids, list) else [message_ids]
    max_id = max(ids)
    try:
        await client.forward_messages(BOT_USERNAME, ids, from_peer=peer)
        await mark_read(client, peer, max_id)
        return
    except FloodWaitError as e:
        log("FLOOD", f"wait {e.seconds}s")
        await asyncio.sleep(e.seconds + 1)
        try:
            await client.forward_messages(BOT_USERNAME, ids, from_peer=peer)
            await mark_read(client, peer, max_id)
            return
        except Exception:
            pass
    except Exception as e:
        err = str(e)
        # канал запрещает пересылку — копируем вручную
        if "noforwards" in err.lower() or "forward" in err.lower():
            log("COPY", f"noforwards, copying {ids}")
        else:
            log("WARN", f"forward failed: {err[:80]}")

    # fallback: скопировать каждое сообщение
    for mid in ids:
        try:
            msg = await client.get_messages(peer, ids=mid)
            if msg:
                await copy_message(client, msg)
        except Exception as ce:
            log("ERROR", f"copy failed mid={mid}: {ce}")


async def copy_message(client, msg) -> None:
    caption = msg.text or ""
    try:
        if msg.media:
            await client.send_file(BOT_USERNAME, msg.media, caption=caption)
        elif caption:
            await client.send_message(BOT_USERNAME, caption)
    except Exception as e:
        log("ERROR", f"copy_message: {e}")

# ── album sender ──────────────────────────────────────────────────────────────
async def flush_album(client, group_id: int, peer) -> None:
    await asyncio.sleep(ALBUM_WAIT)
    ids = album_buffer.pop(group_id, [])
    album_tasks.pop(group_id, None)
    if not ids:
        return
    ids.sort()
    cid = getattr(peer, "channel_id", 0)
    label = CHANNEL_LABELS.get(cid, str(group_id))
    log("ALBUM", f"{label} group={group_id} n={len(ids)}")
    await safe_forward(client, peer, ids)


def task_done_callback(task: asyncio.Task) -> None:
    try:
        task.result()
    except asyncio.CancelledError:
        pass
    except Exception as e:
        log("TASK_ERR", str(e)[:120])

# ── main ──────────────────────────────────────────────────────────────────────
async def main() -> None:
    log("START", "userbot starting")

    client = TelegramClient(
        SESSION_NAME, API_ID, API_HASH,
        catch_up=True,          # догоняет пропущенные сообщения после реконнекта
        receive_updates=True,
    )
    await client.connect()

    if not await client.is_user_authorized():
        log("ERROR", "Not authorized! Run: python3 auth.py")
        return

    me = await client.get_me()
    log("READY", f"logged in as {me.first_name} | {len(ALLOWED_IDS)} channels → {BOT_USERNAME}")

    @client.on(events.NewMessage())
    async def handler(event: events.NewMessage.Event) -> None:
        if not event.is_channel:
            return
        cid = int(getattr(event.message.peer_id, "channel_id", 0))
        if cid not in ALLOWED_IDS:
            return

        label = CHANNEL_LABELS.get(cid, str(cid))
        peer  = event.message.peer_id

        if event.grouped_id:
            gid = event.grouped_id
            album_buffer.setdefault(gid, []).append(event.id)
            existing = album_tasks.get(gid)
            if existing and not existing.done():
                existing.cancel()
            t = asyncio.create_task(flush_album(client, gid, peer))
            t.add_done_callback(task_done_callback)
            album_tasks[gid] = t
            log("IN", f"{label} mid={event.id} album gid={gid}")
            return

        log("IN", f"{label} mid={event.id}")
        t = asyncio.create_task(safe_forward(client, peer, event.id))
        t.add_done_callback(task_done_callback)

    await client.run_until_disconnected()

asyncio.run(main())

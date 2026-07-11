"""Одноразовый скрипт авторизации. После успешного входа создаст userbot.session."""
import asyncio
from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError
from config import API_ID, API_HASH, PHONE, SESSION_NAME

async def main():
    client = TelegramClient(SESSION_NAME, API_ID, API_HASH)
    await client.connect()
    print(f"Подключено к Telegram")

    if await client.is_user_authorized():
        print("✅ Уже авторизован! Можно запускать userbot.py")
        await client.disconnect()
        return

    print(f"Отправляю код на {PHONE}...")
    await client.send_code_request(PHONE)

    code = input("Введите код из Telegram: ").strip()

    try:
        await client.sign_in(PHONE, code)
    except SessionPasswordNeededError:
        password = input("Введите пароль 2FA: ").strip()
        await client.sign_in(password=password)

    print("✅ Авторизация успешна! Теперь запускайте: python3 userbot.py")
    await client.disconnect()

asyncio.run(main())

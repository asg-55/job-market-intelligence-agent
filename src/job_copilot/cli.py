from __future__ import annotations

import argparse
import asyncio
import json
import shutil
from dataclasses import asdict
from pathlib import Path

import httpx

from .bootstrap import build_container
from .config import get_settings


async def _run(pages: int, trigger: str = "cli") -> None:
    current = build_container(get_settings())
    try:
        summary = await current.pipeline.run(
            current.profile_store.load(), pages=pages, trigger=trigger
        )
        print(json.dumps(asdict(summary), ensure_ascii=False, indent=2))
    finally:
        await current.close()


async def _watch(pages: int, interval: int) -> None:
    if interval < 60:
        raise SystemExit("Interval must be at least 60 seconds")
    while True:
        try:
            await _run(pages, trigger="scheduler")
        except Exception as error:
            print(f"Monitoring run failed: {error!r}", flush=True)
        await asyncio.sleep(interval)


async def _telegram_chat_ids() -> None:
    token = get_settings().telegram_bot_token
    if not token:
        raise SystemExit("Set TELEGRAM_BOT_TOKEN in .env first")
    async with httpx.AsyncClient(
        base_url=f"https://api.telegram.org/bot{token}/", timeout=20
    ) as client:
        response = await client.get("getUpdates")
        response.raise_for_status()
        updates = response.json().get("result", [])
    chats: dict[int, dict] = {}
    for update in updates:
        message = update.get("message") or update.get("edited_message")
        if message and message.get("chat"):
            chat = message["chat"]
            chats[chat["id"]] = chat
    if not chats:
        print("No chats found. Send /start to the bot and run this command again.")
        return
    for chat_id, chat in chats.items():
        label = chat.get("username") or chat.get("title") or chat.get("first_name") or "chat"
        print(f"TELEGRAM_CHAT_ID={chat_id}  # {label}")


async def _telegram_bot() -> None:
    current = build_container(get_settings())
    if current.notifier is None or current.telegram_bot is None:
        await current.close()
        raise SystemExit("Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in .env first")
    allowed_chat_id = str(current.settings.telegram_chat_id)
    offset = None
    try:
        while True:
            try:
                updates = await current.notifier.get_updates(offset)
                for update in updates:
                    offset = int(update["update_id"]) + 1
                    message = update.get("message")
                    if not message:
                        continue
                    if str(message.get("chat", {}).get("id", "")) != allowed_chat_id:
                        continue
                    await current.telegram_bot.handle_message(message)
            except httpx.HTTPError as error:
                print(f"Telegram polling failed: {error!r}", flush=True)
                await asyncio.sleep(5)
    finally:
        await current.close()


def _init_profile(destination: Path) -> None:
    source = Path("config/profile.example.json")
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        raise SystemExit(f"Profile already exists: {destination}")
    shutil.copyfile(source, destination)
    print(f"Created {destination}")


def main() -> None:
    parser = argparse.ArgumentParser(prog="job-copilot")
    subparsers = parser.add_subparsers(dest="command", required=True)
    run_parser = subparsers.add_parser("run", help="Run vacancy monitoring once")
    run_parser.add_argument("--pages", type=int, default=1)
    watch_parser = subparsers.add_parser("watch", help="Run monitoring on a fixed interval")
    watch_parser.add_argument("--pages", type=int, default=1)
    watch_parser.add_argument("--interval", type=int, default=43200, help="Seconds between runs")
    init_parser = subparsers.add_parser("init-profile", help="Create an editable profile")
    init_parser.add_argument("--path", type=Path, default=Path("config/profile.json"))
    subparsers.add_parser("telegram-chat-id", help="Find chat IDs from recent bot messages")
    subparsers.add_parser("telegram-bot", help="Run the interactive Telegram bot")
    args = parser.parse_args()
    if args.command == "run":
        asyncio.run(_run(args.pages))
    elif args.command == "watch":
        asyncio.run(_watch(args.pages, args.interval))
    elif args.command == "init-profile":
        _init_profile(args.path)
    elif args.command == "telegram-chat-id":
        asyncio.run(_telegram_chat_ids())
    elif args.command == "telegram-bot":
        asyncio.run(_telegram_bot())


if __name__ == "__main__":
    main()

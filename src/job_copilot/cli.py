from __future__ import annotations

import argparse
import asyncio
import json
import shutil
from dataclasses import asdict
from pathlib import Path

from .bootstrap import build_container
from .config import get_settings


async def _run(pages: int) -> None:
    current = build_container(get_settings())
    try:
        summary = await current.pipeline.run(current.profile, pages=pages)
        print(json.dumps(asdict(summary), ensure_ascii=False, indent=2))
    finally:
        await current.close()


async def _watch(pages: int, interval: int) -> None:
    if interval < 60:
        raise SystemExit("Interval must be at least 60 seconds")
    while True:
        try:
            await _run(pages)
        except Exception as error:
            print(f"Monitoring run failed: {error!r}", flush=True)
        await asyncio.sleep(interval)


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
    args = parser.parse_args()
    if args.command == "run":
        asyncio.run(_run(args.pages))
    elif args.command == "watch":
        asyncio.run(_watch(args.pages, args.interval))
    elif args.command == "init-profile":
        _init_profile(args.path)


if __name__ == "__main__":
    main()

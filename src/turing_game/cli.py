"""Small diagnostic CLI sharing the same client as the MCP server."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys

from .client import TuringClient, TuringClientError


async def _run(args: argparse.Namespace) -> int:
    client = TuringClient()
    try:
        if args.command == "start":
            print(json.dumps(await client.start_match(args.nickname), ensure_ascii=False))
            while True:
                result = await client.wait_event(args.wait)
                print(json.dumps(result, ensure_ascii=False))
                if result["state"]["state"] in {"result", "closed", "error"}:
                    break
        elif args.command == "state":
            print(json.dumps(await client.get_state(), ensure_ascii=False))
        else:
            raise TuringClientError("CLI 当前仅支持 start 和 state；聊天请使用 MCP")
        return 0
    except TuringClientError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1
    finally:
        await client.close()


def main() -> None:
    parser = argparse.ArgumentParser(prog="turing-game")
    sub = parser.add_subparsers(dest="command", required=True)
    start = sub.add_parser("start")
    start.add_argument("--nickname")
    start.add_argument("--wait", type=float, default=20.0)
    sub.add_parser("state")
    raise SystemExit(asyncio.run(_run(parser.parse_args())))


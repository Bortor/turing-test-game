"""Run exactly one authorized live validation round.

This script is intentionally finite and conservative. It is for protocol
validation, not an autonomous match loop.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from turing_game.client import TuringClient, TuringClientError


def emit(kind: str, payload: dict) -> None:
    safe = {"event": kind, **payload}
    print(json.dumps(safe, ensure_ascii=False), flush=True)


async def run_once(args: argparse.Namespace) -> int:
    client = TuringClient()
    submitted = False
    try:
        state = await client.start_match()
        emit("started", {"state": state})
        queue_deadline = asyncio.get_running_loop().time() + args.queue_timeout
        sent_followup = False
        while asyncio.get_running_loop().time() < queue_deadline:
            update = await client.wait_event(args.wait)
            emit("update", update)
            snapshot = update["state"]
            current = snapshot["state"]
            if current == "active":
                if not snapshot["first_message_sent"]:
                    await client.send_message(args.opening)
                    emit("opening_sent", {})
                if snapshot.get("peer_message_count", 0) >= 1 and not sent_followup:
                    await client.send_message(args.followup)
                    sent_followup = True
                    emit("followup_sent", {})
                if snapshot["guess_unlock_remaining_sec"] in (None, 0):
                    await client.submit_guess(args.guess)
                    submitted = True
                    emit("guess_submitted", {"guess": args.guess})
                    break
            elif current in {"result", "error", "closed"}:
                break

        if not submitted and client.snapshot()["state"] not in {"result", "closed", "error"}:
            await client.submit_guess(args.guess)
            submitted = True
            emit("guess_submitted", {"guess": args.guess})

        result_deadline = asyncio.get_running_loop().time() + args.result_timeout
        while asyncio.get_running_loop().time() < result_deadline:
            update = await client.wait_event(args.wait)
            emit("result_wait", update)
            if update["state"]["state"] in {"result", "closed", "error"}:
                return 0
        emit("result_timeout", {"state": client.snapshot()})
        return 2
    except TuringClientError as exc:
        emit("client_error", {"message": str(exc), "state": client.snapshot()})
        return 1
    finally:
        if client.snapshot()["state"] != "closed":
            await client.leave()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--queue-timeout", type=float, default=360.0)
    parser.add_argument("--result-timeout", type=float, default=90.0)
    parser.add_argument("--wait", type=float, default=15.0)
    parser.add_argument("--guess", choices=("human", "ai"), default="human")
    parser.add_argument("--opening", default="你好，这是一条协议验证消息。")
    parser.add_argument("--followup", default="收到，感谢回复。")
    raise SystemExit(asyncio.run(run_once(parser.parse_args())))


if __name__ == "__main__":
    main()

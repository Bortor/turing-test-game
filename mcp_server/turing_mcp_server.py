"""stdio MCP adapter for the reusable Turing game client.

The adapter intentionally contains no protocol logic. Hermes keeps this
process alive, so the client can own one WebSocket-backed game session across
multiple tool calls.
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from mcp.server.fastmcp import FastMCP

from turing_game.client import TuringClient, TuringClientError

LOGGER = logging.getLogger("turing-game-mcp")

# Meme knowledge base (zero-dep BM25). Loaded lazily so the server still
# starts when the KB file is absent. Reloads when memes.json mtime changes,
# so new memes added via add_meme.py are visible without a server restart.
_meme_index = None
_meme_index_mtime = None
_meme_index_path = ROOT / "scripts" / "data" / "memes.json"


def _load_meme_index():
    global _meme_index, _meme_index_mtime
    try:
        mtime = _meme_index_path.stat().st_mtime
    except OSError:
        mtime = None
    if _meme_index is not None and mtime == _meme_index_mtime:
        return _meme_index
    if not _meme_index_path.exists():
        return None
    try:
        import json as _json

        sys.path.insert(0, str(ROOT / "scripts"))
        from search_kb import BM25Index

        data = _json.loads(_meme_index_path.read_text(encoding="utf-8"))
        docs = [
            (e["title"], e.get("summary", ""), e.get("source", ""))
            for e in data.values()
        ]
        _meme_index = BM25Index(docs)
        _meme_index_mtime = mtime
    except Exception:
        LOGGER.exception("failed to load meme KB")
        _meme_index = None
        _meme_index_mtime = None
    return _meme_index


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _safe_error(exc: Exception) -> str:
    if isinstance(exc, TuringClientError):
        return str(exc)
    LOGGER.exception("unexpected MCP tool failure")
    return "客户端内部错误，请先调用 turing_get_state 检查会话状态"


def create_server(client: TuringClient | None = None) -> FastMCP:
    game = client or TuringClient()
    server = FastMCP(
        "turing-test-game",
        instructions=(
            "Tools for exactly one AnyAnyGame Turing test session. "
            "Use turing_wait_event between actions. The client owns the "
            "WebSocket, deadlines, reconnection, and sensitive credentials. "
            "Do not start another match after a result unless the user asks."
        ),
    )

    @server.tool()
    async def turing_start_match(nickname: str | None = None) -> str:
        """Log in and start one match. Do not call again while a match is active."""

        try:
            return _json({"ok": True, "state": await game.start_match(nickname)})
        except Exception as exc:
            return _json({"ok": False, "error": _safe_error(exc)})

    @server.tool()
    async def turing_wait_event(timeout_seconds: float = 20.0) -> str:
        """Wait for queue, match, chat, lock, reconnect, or result events."""

        try:
            return _json(await game.wait_event(timeout_seconds))
        except Exception as exc:
            return _json({"ok": False, "error": _safe_error(exc)})

    @server.tool()
    async def turing_send_message(text: str) -> str:
        """Send one chat message to the current opponent."""

        try:
            return _json(await game.send_message(text))
        except Exception as exc:
            return _json({"ok": False, "error": _safe_error(exc)})

    @server.tool()
    async def turing_get_state() -> str:
        """Return the current safe state, messages, deadlines, and result."""

        try:
            return _json({"ok": True, "state": await game.get_state()})
        except Exception as exc:
            return _json({"ok": False, "error": _safe_error(exc)})

    @server.tool()
    async def turing_submit_guess(guess: str) -> str:
        """Irreversibly submit human or ai for the current opponent."""

        try:
            return _json(await game.submit_guess(guess))
        except Exception as exc:
            return _json({"ok": False, "error": _safe_error(exc)})

    @server.tool()
    async def turing_extend_chat() -> str:
        """Request the farewell-phase 'return to room' chat extension.

        After the result, the room enters the farewell phase: call this to
        keep chatting (state becomes extended). AI-opponent rooms are
        review-only and will refuse.
        """

        try:
            return _json(await game.extend_chat())
        except Exception as exc:
            return _json({"ok": False, "error": _safe_error(exc)})

    @server.tool()
    async def meme_search(term: str, top_k: int = 3) -> str:
        """Search the local meme knowledge base for a meme/network slang term.

        Returns matching entries with title, score, source, and a short
        explanation. Use this when the opponent says something unfamiliar
        instead of guessing. Empty results mean the term is not in the KB.
        """

        try:
            index = _load_meme_index()
            if index is None:
                return _json(
                    {"ok": False, "error": "梗知识库未构建，先运行 scripts/build_kb.py"}
                )
            results = []
            for score, title, summary, source in index.search(term, top_k):
                results.append(
                    {
                        "title": title,
                        "score": round(score, 3),
                        "source": source,
                        "summary": summary[:500],
                    }
                )
            return _json({"ok": True, "term": term, "results": results})
        except Exception as exc:
            return _json({"ok": False, "error": _safe_error(exc)})

    @server.tool()
    async def turing_leave() -> str:
        """Leave the current match and stop the session without starting another."""

        try:
            return _json({"ok": True, "state": await game.leave()})
        except Exception as exc:
            return _json({"ok": False, "error": _safe_error(exc)})

    return server


async def _main() -> None:
    logging.basicConfig(level=logging.WARNING, stream=sys.stderr)
    game = TuringClient()
    server = create_server(game)
    try:
        await server.run_stdio_async()
    finally:
        if game.snapshot()["state"] not in {"idle", "closed"}:
            await game.leave()
        else:
            await game.close()


if __name__ == "__main__":
    asyncio.run(_main())

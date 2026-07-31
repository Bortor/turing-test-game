from __future__ import annotations

import json
import unittest
from pathlib import Path

from turing_game.client import TuringClient
from turing_game.models import GameConfig, GameState


class FixtureReplayTests(unittest.IsolatedAsyncioTestCase):
    async def test_active_round_fixture_reaches_result(self) -> None:
        path = Path(__file__).parent / "fixtures" / "active_round.json"
        events = json.loads(path.read_text(encoding="utf-8"))
        client = TuringClient(GameConfig(password="test-only"))
        sent: list[dict] = []

        async def fake_send(payload: dict) -> None:
            sent.append(payload)

        client._ws = object()
        client._send_ws = fake_send  # type: ignore[method-assign]
        client._ticket_id = "ticket-fixture"
        client._session_id = "session-fixture"
        for event in events:
            await client._handle_ws_message(event)

        self.assertEqual(client.state, GameState.RESULT)
        self.assertEqual(client.snapshot()["message_count"], 3)
        self.assertTrue(client.snapshot()["peer_locked"])
        self.assertTrue(client.snapshot()["result"]["correct"])
        await client.close()


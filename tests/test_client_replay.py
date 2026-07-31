from __future__ import annotations

import asyncio
import unittest

from turing_game.client import TuringClient
from turing_game.models import GameConfig, GameState


class ClientReplayTests(unittest.IsolatedAsyncioTestCase):
    def make_client(self) -> TuringClient:
        return TuringClient(GameConfig(password="test-only"))

    async def test_match_to_room_to_active(self) -> None:
        client = self.make_client()
        sent: list[dict] = []

        async def fake_send(payload: dict) -> None:
            sent.append(payload)

        client._send_ws = fake_send  # type: ignore[method-assign]
        client._ws = object()
        client._ticket_id = "ticket-fixture"
        client._session_id = "session-fixture"
        await client._handle_ws_message(
            {
                "type": "match.update",
                "status": {
                    "status": "matched",
                    "roomId": "room-fixture",
                    "guessUnlocksAt": 100000,
                    "serverNow": 1000,
                },
            }
        )
        self.assertEqual(client.state, GameState.MATCHED)
        self.assertEqual(sent[-1]["type"], "room.subscribe")

        await client._handle_ws_message(
            {
                "type": "room.subscribed",
                "room": {
                    "state": "active",
                    "serverNow": 1000,
                    "messages": [
                        {"id": "m1", "sender": "system", "text": "connected"},
                        {"id": "m2", "sender": "peer", "text": "你好"},
                    ],
                },
            }
        )
        self.assertEqual(client.state, GameState.ACTIVE)
        self.assertEqual(client.snapshot()["message_count"], 2)
        self.assertFalse(client.snapshot()["can_guess"])

        await client._handle_ws_message(
            {
                "type": "room.update",
                "room": {
                    "state": "active",
                    "messages": [{"id": "m2", "sender": "peer", "text": "你好"}],
                },
            }
        )
        self.assertEqual(client.snapshot()["message_count"], 2)
        await client.close()

    async def test_wait_event_returns_replayed_events(self) -> None:
        client = self.make_client()
        await client._publish({"event": "fixture", "value": 1})
        result = await client.wait_event(0.1)
        self.assertFalse(result["timed_out"])
        self.assertEqual(result["events"][0]["event"], "fixture")
        second = await client.wait_event(0.1)
        self.assertTrue(second["timed_out"])

    async def test_guess_response_can_finish_round(self) -> None:
        client = self.make_client()
        client._token = "test-token"
        client._room_id = "room-fixture"
        client._session_id = "session-fixture"

        async def fake_http(path, *, method="GET", body=None, auth=False):
            return {"result": {"correct": True}}

        client._http_json = fake_http  # type: ignore[method-assign]
        result = await client.submit_guess("human")
        self.assertEqual(client.state, GameState.RESULT)
        self.assertTrue(result["state"]["result"]["correct"])
        self.assertEqual(result["state"]["result"]["actualIdentity"], "human")
        await client.close()

    async def test_room_updates_do_not_reopen_a_locked_session(self) -> None:
        client = self.make_client()
        client._my_guess = "human"
        client._room_id = "room-fixture"
        await client._handle_ws_message(
            {"type": "room.update", "room": {"state": "active", "serverNow": 1000}}
        )
        self.assertEqual(client.state, GameState.LOCKED_WAIT)
        self.assertFalse(client.snapshot()["can_send"])
        await client.close()


if __name__ == "__main__":
    unittest.main()

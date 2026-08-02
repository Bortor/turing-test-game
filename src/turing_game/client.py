"""Async HTTP/WebSocket client and resilient game state machine."""

from __future__ import annotations

import asyncio
import json
import logging
import time
import urllib.error
import urllib.request
import uuid
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Awaitable, Callable

try:
    from websockets.asyncio.client import connect as websocket_connect
except ImportError:  # pragma: no cover - compatibility with older websockets
    from websockets import connect as websocket_connect  # type: ignore

from .models import GameConfig, GameState

LOGGER = logging.getLogger(__name__)


class TuringClientError(RuntimeError):
    """An expected client or remote-service failure with a safe message."""

    def __init__(self, message: str, *, status: int | None = None, code: str | None = None):
        super().__init__(message)
        self.status = status
        self.code = code


@dataclass(slots=True)
class _PendingRequest:
    future: asyncio.Future[dict[str, Any]]
    created_at: float


class TuringClient:
    """Own exactly one game session and expose safe, structured snapshots."""

    _STATUS_MAP = {
        "queued": GameState.QUEUED,
        "waiting": GameState.WAITING,
        "calibrating": GameState.CALIBRATING,
        "matched": GameState.MATCHED,
        "active": GameState.ACTIVE,
        "locked": GameState.LOCKED_WAIT,
        "locked_wait": GameState.LOCKED_WAIT,
        # 2026-08-02 服务端新增房间状态：ended=结算完成（等回到房间/查看结果），
        # extended=告别期（双方可继续聊天）
        "ended": GameState.RESULT,
        "extended": GameState.EXTENDED,
        "result": GameState.RESULT,
        "complete": GameState.RESULT,
        "completed": GameState.RESULT,
        "closed": GameState.CLOSED,
        "disconnected": GameState.RESULT,
    }

    def __init__(self, config: GameConfig | None = None):
        self.config = config or GameConfig.from_env()
        self.state = GameState.IDLE
        self._token: str | None = None
        self._ticket_id: str | None = None
        self._session_id: str | None = None
        self._room_id: str | None = None
        self._queue_position: int | None = None
        self._ws: Any = None
        self._ws_task: asyncio.Task[None] | None = None
        self._opening_guard_task: asyncio.Task[None] | None = None
        self._stop_event: asyncio.Event | None = None
        self._send_lock = asyncio.Lock()
        self._condition = asyncio.Condition()
        self._event_log: deque[tuple[int, dict[str, Any]]] = deque(maxlen=200)
        self._event_seq = 0
        self._last_wait_seq = 0
        self._pending: dict[str, _PendingRequest] = {}
        self._seen_message_ids: set[str] = set()
        self._messages: list[dict[str, Any]] = []
        self._first_message_deadline_ms: int | None = None
        self._guess_unlocks_at_ms: int | None = None
        self._ends_at_ms: int | None = None
        self._server_now_ms: int | None = None
        self._server_now_monotonic: float | None = None
        self._first_message_sent = False
        self._last_message_sent_monotonic: float | None = None
        self._my_guess: str | None = None
        self._opponent_guess: str | None = None
        self._peer_locked = False
        self._first_locked_by: str | None = None
        self._result: dict[str, Any] | None = None
        self._last_error: str | None = None
        self._last_sequence = 0
        self._room_subscribe_sent = False
        # 告别期状态（2026-08-02）：服务端房间对象新增 chatExtension 字段
        self._chat_extension: dict[str, Any] | None = None

    # ------------------------------------------------------------------
    # Public lifecycle
    # ------------------------------------------------------------------

    async def start_match(self, nickname: str | None = None) -> dict[str, Any]:
        """Authenticate, create a ticket, and begin the WS subscription."""

        if self.state not in {GameState.IDLE, GameState.CLOSED, GameState.RESULT, GameState.ERROR}:
            raise TuringClientError("已有一局正在进行，先调用 turing_leave")
        if not self.config.password:
            raise TuringClientError("未配置 TT_PW 或 TURING_PASSWORD")
        if not self.config.username:
            raise TuringClientError("未配置 TT_USERNAME")
        await self._reset_session()
        self.state = GameState.AUTHENTICATING
        await self._publish({"event": "state", "state": self.state.value})
        await self._login()
        body = {
            "nickname": nickname or self.config.nickname,
            "protocolVersion": self.config.protocol_version,
            "clientVersion": self.config.client_version,
            "chatDurationSec": self.config.chat_duration_sec,
            "matchTimeoutSec": self.config.match_timeout_sec,
            "allowAnonymousChatResearch": self.config.allow_anonymous_chat_research,
            "registeredPrivacyNoticeVersion": self.config.registered_privacy_notice_version,
        }
        data = await self._http_json("/api/turing/start", method="POST", body=body, auth=True)
        ticket = data.get("ticket") or {}
        self._ticket_id = ticket.get("ticketId")
        self._session_id = ticket.get("sessionId")
        if not self._ticket_id or not self._session_id:
            raise TuringClientError("匹配接口没有返回有效票据")
        self._apply_match_status(ticket)
        self._stop_event = asyncio.Event()
        self._ws_task = asyncio.create_task(self._run_ws(), name="turing-game-ws")
        await self._publish(
            {
                "event": "match_started",
                "state": self.state.value,
                "queue_position": self._queue_position,
            }
        )
        return self.snapshot()

    async def wait_event(self, timeout_seconds: float | None = None) -> dict[str, Any]:
        """Wait for new normalized events and return them with a safe snapshot."""

        timeout = max(0.1, min(float(timeout_seconds or self.config.event_wait_default_sec), 60.0))
        deadline = time.monotonic() + timeout
        while True:
            fresh = [event for seq, event in self._event_log if seq > self._last_wait_seq]
            if fresh:
                self._last_wait_seq = self._event_seq
                return {"ok": True, "timed_out": False, "events": fresh, "state": self.snapshot()}
            if self.state in {GameState.CLOSED, GameState.ERROR}:
                return {
                    "ok": True,
                    "timed_out": True,
                    "finished": True,
                    "events": [],
                    "state": self.snapshot(),
                }
            # 结算后有告别期（chatExtension）时不立即结束：继续等 room.update
            # （对方回到房间 / 对方离开 / 告别期状态变化都会下发）
            if self.state == GameState.RESULT and self._chat_extension is None:
                return {
                    "ok": True,
                    "timed_out": True,
                    "finished": True,
                    "events": [],
                    "state": self.snapshot(),
                }
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return {"ok": True, "timed_out": True, "events": [], "state": self.snapshot()}
            async with self._condition:
                try:
                    await asyncio.wait_for(self._condition.wait(), timeout=remaining)
                except asyncio.TimeoutError:
                    return {"ok": True, "timed_out": True, "events": [], "state": self.snapshot()}

    async def send_message(self, text: str) -> dict[str, Any]:
        """Send one chat message and wait for its server acknowledgement."""

        message = str(text).strip()
        if not message:
            raise TuringClientError("消息不能为空")
        if len(message) > 2000:
            raise TuringClientError("消息过长，最多 2000 个字符")
        if self.state not in {
            GameState.ACTIVE,
            GameState.MATCHED,
            GameState.LOCKED_WAIT,
            GameState.EXTENDED,
        }:
            raise TuringClientError("当前不在可聊天状态")
        if self.state == GameState.EXTENDED and not self._chat_extension_can_send():
            raise TuringClientError("当前告别期不可发送消息（只读/等待对方）")
        if not self._room_id:
            raise TuringClientError("房间尚未建立")
        if self._last_message_sent_monotonic is not None:
            cooldown = self.config.message_cooldown_sec - (
                time.monotonic() - self._last_message_sent_monotonic
            )
            if cooldown > 0:
                await asyncio.sleep(cooldown)
        request_id = str(uuid.uuid4())
        client_message_id = str(uuid.uuid4())
        response_future: asyncio.Future[dict[str, Any]] = asyncio.get_running_loop().create_future()
        self._pending[request_id] = _PendingRequest(response_future, time.monotonic())
        try:
            await self._send_ws(
                {
                    "type": "message.send",
                    "requestId": request_id,
                    "roomId": self._room_id,
                    "sessionId": self._session_id,
                    "clientMessageId": client_message_id,
                    "text": message,
                }
            )
            try:
                ack = await asyncio.wait_for(response_future, timeout=10.0)
            except asyncio.TimeoutError as exc:
                raise TuringClientError("消息发送确认超时") from exc
            if not ack.get("ok", False):
                raise TuringClientError(ack.get("error") or "消息发送失败")
            self._first_message_sent = True
            self._last_message_sent_monotonic = time.monotonic()
            self._remember_message(ack.get("message"), fallback={"sender": "self", "text": message})
            await self._publish({"event": "message_sent", "text": message})
            return {"ok": True, "state": self.snapshot()}
        except TuringClientError as exc:
            # HTTP fallback：WS 不可用/超时时直接 POST（前端同款路径）
            try:
                fallback = await self._http_json(
                    f"/api/turing/rooms/{self._room_id}/messages",
                    method="POST",
                    body={
                        "sessionId": self._session_id,
                        "clientMessageId": client_message_id,
                        "text": message,
                    },
                    auth=True,
                )
                self._first_message_sent = True
                self._last_message_sent_monotonic = time.monotonic()
                self._remember_message(
                    fallback.get("message"),
                    fallback={"sender": "self", "text": message},
                )
                await self._publish({"event": "message_sent", "text": message})
                return {"ok": True, "state": self.snapshot(), "fallback": True}
            except TuringClientError:
                raise exc
        finally:
            self._pending.pop(request_id, None)

    async def submit_guess(self, guess: str) -> dict[str, Any]:
        """Submit an irreversible human/AI guess through the HTTP API."""

        normalized = str(guess).strip().lower()
        if normalized in {"h", "human", "真人"}:
            normalized = "human"
        elif normalized in {"a", "ai", "机器人"}:
            normalized = "ai"
        else:
            raise TuringClientError("guess 必须是 human 或 ai")
        if not self._room_id or not self._session_id:
            raise TuringClientError("当前没有可判定的房间")
        if self._my_guess:
            raise TuringClientError("本局已经提交过判定")
        if self._guess_unlocks_at_ms is not None:
            server_now = self._server_now_ms or int(time.time() * 1000)
            if self._server_now_monotonic is not None:
                server_now += int((time.monotonic() - self._server_now_monotonic) * 1000)
            if server_now < self._guess_unlocks_at_ms:
                remaining = max(1, int((self._guess_unlocks_at_ms - server_now) / 1000))
                raise TuringClientError(f"判定尚未解锁，还需约 {remaining} 秒")
        data = await self._http_json(
            f"/api/turing/rooms/{self._room_id}/guess",
            method="POST",
            body={"sessionId": self._session_id, "guess": normalized},
            auth=True,
        )
        self._my_guess = normalized
        # 响应是完整房间对象（2026-08-02 告别期）：结算响应可能已带 chatExtension，
        # 提前解析，否则 RESULT 状态下 wait_event 会立即 finished 丢告别期事件
        if isinstance(data.get("chatExtension"), dict):
            self._chat_extension = dict(data["chatExtension"])
        if str(data.get("state")) == "extended":
            self.state = GameState.EXTENDED
        result = self._extract_result(data)
        result = self._enrich_result(result)
        if result:
            self._result = result
            self._opponent_guess = result.get("opponentGuess")
            self.state = GameState.RESULT
            self._dump_session(reason="result")
        elif self._peer_locked:
            self.state = GameState.RESULT
            self._dump_session(reason="result")
        else:
            # 防御：响应已标记 extended（告别期）时不降级为 LOCKED_WAIT
            if self.state != GameState.EXTENDED:
                self.state = GameState.LOCKED_WAIT
        await self._publish({"event": "guess_submitted", "guess": normalized, "result": result})
        return {"ok": True, "state": self.snapshot()}

    async def extend_chat(self) -> dict[str, Any]:
        """发起/接受告别期「回到房间」，继续聊天（2026-08-02 服务端新功能）。

        结算后房间 state=ended，调用此接口进入告别期（state=extended），
        双方可继续聊天，5 分钟后彻底关闭；AI 对局为 reviewOnly 不可扩展。
        """

        if not self._room_id or not self._session_id:
            raise TuringClientError("当前没有可扩展的房间")
        data = await self._http_json(
            f"/api/turing/rooms/{self._room_id}/extend-chat",
            method="POST",
            body={"sessionId": self._session_id},
            auth=True,
        )
        # 响应通常是更新后的房间对象；也可能直接返回错误（AI 局/reviewOnly）
        room = data.get("room") if isinstance(data.get("room"), dict) else data
        self._apply_room(room)
        await self._publish({"event": "chat_extended", "state": self.state.value})
        return {"ok": True, "state": self.snapshot()}

    async def get_state(self) -> dict[str, Any]:
        return self.snapshot()

    async def leave(self) -> dict[str, Any]:
        """Leave the current ticket/room and stop all background tasks."""

        if self._ticket_id and self._session_id and self._token:
            try:
                await self._http_json(
                    "/api/turing/leave",
                    method="POST",
                    body={
                        "ticketId": self._ticket_id,
                        "roomId": self._room_id,
                        "sessionId": self._session_id,
                    },
                    auth=True,
                )
            except TuringClientError as exc:
                LOGGER.debug("Leave request failed: %s", exc)
        await self._shutdown_tasks()
        self._dump_session(reason="leave")
        self.state = GameState.CLOSED
        await self._publish({"event": "closed", "state": self.state.value})
        return self.snapshot()

    async def close(self) -> None:
        await self._shutdown_tasks()

    # ------------------------------------------------------------------
    # Safe state and protocol helpers
    # ------------------------------------------------------------------

    def snapshot(self) -> dict[str, Any]:
        now = int(time.time() * 1000)
        server_now = self._server_now_ms or now
        if self._server_now_ms is not None and self._server_now_monotonic is not None:
            server_now += int((time.monotonic() - self._server_now_monotonic) * 1000)

        def remaining(deadline: int | None) -> int | None:
            if deadline is None:
                return None
            return max(0, int((deadline - server_now) / 1000))

        peer_messages = [
            message
            for message in self._messages
            if message.get("sender") not in {"system", "self", "me", "player"}
        ]
        guess_unlocked = self._guess_is_unlocked(server_now)
        return {
            "state": self.state.value,
            "queue_position": self._queue_position,
            "message_count": len(self._messages),
            "messages": list(self._messages[-50:]),
            "peer_message_count": len(peer_messages),
            "first_message_sent": self._first_message_sent,
            "first_message_remaining_sec": remaining(self._first_message_deadline_ms),
            "guess_unlock_remaining_sec": remaining(self._guess_unlocks_at_ms),
            "room_remaining_sec": remaining(self._ends_at_ms),
            "can_send": bool(self._room_id)
            and (
                self.state in {GameState.ACTIVE, GameState.MATCHED}
                or (
                    self.state == GameState.EXTENDED
                    and self._chat_extension_can_send()
                )
            ),
            "chat_extension": self._chat_extension,
            "can_guess": bool(self._room_id)
            and not self._my_guess
            and guess_unlocked
            and self.state in {GameState.ACTIVE, GameState.MATCHED, GameState.LOCKED_WAIT},
            "my_guess": self._my_guess,
            "opponent_guess": self._opponent_guess,
            "peer_locked": self._peer_locked,
            "first_locked_by": self._first_locked_by,
            "result": self._result,
            "last_error": self._last_error,
        }

    def _dump_session(self, *, reason: str) -> None:
        """Persist the full message log for the finished session.

        Best-effort and silent: a failed write must never affect gameplay.
        """
        if not self._messages:
            return
        try:
            directory = Path(self.config.session_log_dir)
            directory.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
            path = directory / f"{stamp}_{reason}.md"
            lines = [
                "# Turing Test 对局记录",
                "",
                f"- 开始时间: {datetime.fromtimestamp(self._messages[0].get('created_at', 0) / 1000).strftime('%Y-%m-%d %H:%M:%S') if self._messages[0].get('created_at') else '未知'}",
                f"- 消息数: {len(self._messages)}",
                f"- 我的判定: {self._my_guess or '无'}",
                f"- 对方对我的判定: {self._opponent_guess or '无'}",
                f"- 结果: {json.dumps(self._result, ensure_ascii=False) if self._result else '未知'}",
                "",
                "## 消息记录",
                "",
            ]
            for message in self._messages:
                sender = message.get("sender", "?")
                text = str(message.get("text", "")).replace("\n", " ")
                created = message.get("created_at")
                when = (
                    datetime.fromtimestamp(created / 1000).strftime("%H:%M:%S")
                    if created
                    else "??:??:??"
                )
                lines.append(f"**[{when}] {sender}**: {text}")
                lines.append("")
            path.write_text("\n".join(lines), encoding="utf-8")
            LOGGER.debug("Session dumped to %s", path)
        except Exception:
            LOGGER.exception("failed to dump session log")

    async def _reset_session(self) -> None:
        await self._shutdown_tasks()
        self.state = GameState.IDLE
        self._token = None
        self._ticket_id = None
        self._session_id = None
        self._room_id = None
        self._queue_position = None
        self._event_log.clear()
        self._event_seq = 0
        self._last_wait_seq = 0
        self._pending.clear()
        self._seen_message_ids.clear()
        self._messages.clear()
        self._first_message_deadline_ms = None
        self._guess_unlocks_at_ms = None
        self._ends_at_ms = None
        self._server_now_ms = None
        self._server_now_monotonic = None
        self._first_message_sent = False
        self._last_message_sent_monotonic = None
        self._my_guess = None
        self._opponent_guess = None
        self._peer_locked = False
        self._first_locked_by = None
        self._result = None
        self._last_error = None
        self._last_sequence = 0
        self._room_subscribe_sent = False
        self._chat_extension = None

    async def _login(self) -> None:
        data = await self._http_json(
            "/api/auth/turing-login",
            method="POST",
            body={"identifier": self.config.username, "password": self.config.password},
            auth=False,
        )
        token = data.get("token")
        if not token:
            raise TuringClientError("登录响应没有 token")
        self._token = str(token)

    async def _http_json(
        self,
        path: str,
        *,
        method: str = "GET",
        body: dict[str, Any] | None = None,
        auth: bool = False,
    ) -> dict[str, Any]:
        return await asyncio.to_thread(self._http_json_sync, path, method, body, auth)

    def _http_json_sync(
        self, path: str, method: str, body: dict[str, Any] | None, auth: bool
    ) -> dict[str, Any]:
        headers = {
            "User-Agent": "turing-test-game/0.1",
            "Content-Type": "application/json",
            "Origin": self.config.base_url,
            "Referer": f"{self.config.base_url}/turing-test",
            "X-Visitor-Id": self.config.visitor_id,
        }
        if auth:
            if not self._token:
                raise TuringClientError("尚未登录")
            headers["Authorization"] = f"Bearer {self._token}"
        raw = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
        request = urllib.request.Request(
            f"{self.config.base_url}{path}", data=raw, headers=headers, method=method
        )
        try:
            with urllib.request.urlopen(request, timeout=self.config.http_timeout_sec) as response:
                payload = response.read().decode("utf-8", errors="replace")
                return self._decode_json(payload)
        except urllib.error.HTTPError as exc:
            payload = exc.read().decode("utf-8", errors="replace")
            data = self._decode_json(payload)
            message = str(data.get("error") or data.get("message") or f"HTTP {exc.code}")
            raise TuringClientError(message, status=exc.code, code=data.get("code")) from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise TuringClientError("网络请求失败") from exc

    @staticmethod
    def _decode_json(payload: str) -> dict[str, Any]:
        try:
            value = json.loads(payload)
        except json.JSONDecodeError as exc:
            raise TuringClientError("服务端返回了非 JSON 响应") from exc
        if not isinstance(value, dict):
            raise TuringClientError("服务端返回格式无效")
        return value

    async def _run_ws(self) -> None:
        delay = 1.0
        while self._stop_event and not self._stop_event.is_set():
            try:
                headers = {
                    "Origin": self.config.base_url,
                    "User-Agent": "turing-test-game/0.1",
                }
                async with websocket_connect(
                    self.config.ws_url,
                    additional_headers=headers,
                    open_timeout=self.config.ws_open_timeout_sec,
                    ping_interval=20,
                    ping_timeout=20,
                ) as websocket:
                    self._ws = websocket
                    delay = 1.0
                    await self._publish({"event": "websocket_connected"})
                    await self._subscribe_current()
                    async for raw in websocket:
                        try:
                            message = json.loads(raw)
                        except (TypeError, json.JSONDecodeError):
                            await self._publish({"event": "protocol_error", "message": "非 JSON WS 消息"})
                            continue
                        await self._handle_ws_message(message)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self._ws = None
                self._last_error = "WebSocket 连接暂时中断"
                await self._publish({"event": "websocket_error", "message": self._last_error})
                if self.state in {GameState.RESULT, GameState.CLOSED, GameState.ERROR}:
                    return
                await asyncio.sleep(delay)
                delay = min(self.config.ws_reconnect_max_sec, delay * 2)
                LOGGER.debug("WebSocket reconnect after %r", exc)
            finally:
                self._ws = None

    async def _subscribe_current(self) -> None:
        if self._room_id:
            self._room_subscribe_sent = True
            await self._send_ws(
                {
                    "type": "room.subscribe",
                    "requestId": str(uuid.uuid4()),
                    "roomId": self._room_id,
                    "sessionId": self._session_id,
                    "after": 0,
                    "afterSequence": self._last_sequence,
                }
            )
        elif self._ticket_id:
            await self._send_ws(
                {
                    "type": "match.subscribe",
                    "requestId": str(uuid.uuid4()),
                    "ticketId": self._ticket_id,
                    "sessionId": self._session_id,
                }
            )

    async def _subscribe_room(self) -> None:
        if self._ws is None or not self._room_id or self._room_subscribe_sent:
            return
        self._room_subscribe_sent = True
        await self._send_ws(
            {
                "type": "room.subscribe",
                "requestId": str(uuid.uuid4()),
                "roomId": self._room_id,
                "sessionId": self._session_id,
                "after": 0,
                "afterSequence": 0,
            }
        )

    async def _send_ws(self, payload: dict[str, Any]) -> None:
        if self._ws is None:
            raise TuringClientError("WebSocket 尚未连接")
        async with self._send_lock:
            await self._ws.send(json.dumps(payload, ensure_ascii=False))

    async def _handle_ws_message(self, message: dict[str, Any]) -> None:
        message_type = message.get("type")
        request_id = message.get("requestId")
        if request_id in self._pending:
            pending = self._pending[request_id]
            if not pending.future.done():
                pending.future.set_result(message)
        if message_type == "match.update":
            status = message.get("status") if isinstance(message.get("status"), dict) else {}
            self._apply_match_status(status)
            if self._room_id and self.state in {GameState.MATCHED, GameState.ACTIVE}:
                await self._subscribe_room()
            await self._publish(
                {
                    "event": "match_update",
                    "state": self.state.value,
                    "queue_position": self._queue_position,
                }
            )
            return
        if message_type == "room.subscribed":
            room = message.get("room") if isinstance(message.get("room"), dict) else {}
            self._apply_room(room)
            self._room_subscribe_sent = True
            await self._publish({"event": "room_subscribed", "state": self.state.value})
            self._start_opening_guard()
            return
        if message_type == "room.update":
            room = message.get("room") if isinstance(message.get("room"), dict) else message
            self._apply_room(room)
            if self.state == GameState.ACTIVE:
                self._start_opening_guard()
            await self._publish(
                {
                    "event": "room_update",
                    "state": self.state.value,
                    "new_messages": self._messages[-5:],
                    "peer_locked": self._peer_locked,
                    "result": self._result,
                }
            )
            return
        if message_type == "message.ack":
            ack_message = message.get("message")
            self._remember_message(ack_message)
            return
        if message_type == "room.superseded":
            # 该对局已在另一个窗口建立连接：停止订阅并标记错误状态
            self._room_subscribe_sent = True
            self.state = GameState.ERROR
            self._last_error = str(
                message.get("message")
                or message.get("error")
                or "该对局已在另一个窗口建立连接"
            )
            await self._publish({"event": "superseded", "message": self._last_error})
            return
        if message_type in {"match.unsubscribe", "room.unsubscribe"}:
            # 订阅确认/取消通知，无需变更状态
            await self._publish({"event": "unsubscribed", "type": message_type})
            return
        if message_type in {"match.fatal", "room.fatal"}:
            self.state = GameState.ERROR
            self._last_error = str(message.get("error") or message.get("code") or "远端会话失败")
            await self._publish({"event": "fatal", "message": self._last_error})

    def _apply_match_status(self, status: dict[str, Any]) -> None:
        raw_state = status.get("status") or status.get("state")
        mapped = self._STATUS_MAP.get(str(raw_state))
        if mapped:
            self.state = mapped
        if isinstance(status.get("queuePosition"), int):
            self._queue_position = status["queuePosition"]
        if status.get("roomId"):
            self._room_id = str(status["roomId"])
        self._apply_timing(status)

    def _apply_room(self, room: dict[str, Any]) -> None:
        self._apply_timing(room)
        room_state = room.get("state") or room.get("status")
        mapped = self._STATUS_MAP.get(str(room_state))
        if mapped:
            self.state = mapped
        if room.get("roomId") and not self._room_id:
            self._room_id = str(room["roomId"])
        messages = room.get("messages")
        if isinstance(messages, list):
            for message in messages:
                self._remember_message(message)
        peer_locked = room.get("peerLocked")
        if isinstance(peer_locked, bool):
            self._peer_locked = peer_locked
        if room.get("peerGuess") is not None or room.get("peerLockedAt") is not None:
            self._peer_locked = True
        # guessState 隐藏字段：firstLockedBy（谁先锁）/ responseWindowMs / deadlineAt
        guess_state = room.get("guessState")
        if isinstance(guess_state, dict):
            if isinstance(guess_state.get("firstLockedBy"), str):
                self._first_locked_by = guess_state["firstLockedBy"]
            if guess_state.get("opponentLocked") is True:
                self._peer_locked = True
        # 告别期字段（2026-08-02）：available/canSend/reviewOnly/selfReturned/
        # pending/active/finished/opponentDeparted + 各阶段时间戳
        if isinstance(room.get("chatExtension"), dict):
            self._chat_extension = dict(room["chatExtension"])
        result = self._extract_result(room)
        result = self._enrich_result(result)
        if result:
            self._result = result
            self._opponent_guess = result.get("opponentGuess")
            self.state = GameState.RESULT
            self._dump_session(reason="result")
        elif self.state == GameState.EXTENDED:
            pass  # 告别期状态保持，不被下方 LOCKED_WAIT 覆盖
        elif self._my_guess:
            self.state = GameState.LOCKED_WAIT
        elif self.state in {GameState.MATCHED, GameState.CALIBRATING} and self._room_id:
            self.state = GameState.ACTIVE

    def _apply_timing(self, payload: dict[str, Any]) -> None:
        for key, attr in (
            ("firstMessageDeadlineAt", "_first_message_deadline_ms"),
            ("guessUnlocksAt", "_guess_unlocks_at_ms"),
            ("endsAt", "_ends_at_ms"),
            ("serverNow", "_server_now_ms"),
        ):
            value = payload.get(key)
            if isinstance(value, (int, float)):
                setattr(self, attr, int(value))
                if attr == "_server_now_ms":
                    self._server_now_monotonic = time.monotonic()

    def _guess_is_unlocked(self, server_now: int | None = None) -> bool:
        if self._guess_unlocks_at_ms is None:
            return True
        current = server_now or int(time.time() * 1000)
        return current >= self._guess_unlocks_at_ms

    def _chat_extension_can_send(self) -> bool:
        """告别期能否发送消息：chatExtension.canSend === true。"""
        return bool(
            isinstance(self._chat_extension, dict)
            and self._chat_extension.get("canSend") is True
        )

    def _remember_message(
        self, message: Any, *, fallback: dict[str, Any] | None = None
    ) -> None:
        if not isinstance(message, dict):
            message = fallback
        if not isinstance(message, dict):
            return
        message_id = message.get("id")
        if message_id and message_id in self._seen_message_ids:
            return
        if message_id:
            self._seen_message_ids.add(str(message_id))
        sequence = message.get("sequence")
        if isinstance(sequence, int):
            self._last_sequence = max(self._last_sequence, sequence)
        sender = str(message.get("sender") or message.get("from") or "unknown")
        normalized = {
            "sender": sender,
            "text": str(message.get("text") or ""),
        }
        if message.get("createdAt") is not None:
            normalized["created_at"] = message["createdAt"]
        if isinstance(message.get("sequence"), int):
            normalized["sequence"] = message["sequence"]
        if isinstance(message.get("deduplicated"), bool):
            normalized["deduplicated"] = message["deduplicated"]
        self._messages.append(normalized)
        if sender not in {"system", "self", "me", "player"} and normalized["text"]:
            self._peer_locked = self._peer_locked or False
        if sender == "system" and not self._my_guess:
            lower_text = normalized["text"].lower()
            if "一方已经锁定" in normalized["text"] or "one player has locked" in lower_text:
                self._peer_locked = True

    @staticmethod
    def _extract_result(payload: Any) -> dict[str, Any] | None:
        if not isinstance(payload, dict):
            return None
        room = payload.get("room") if isinstance(payload.get("room"), dict) else None
        candidates = [
            payload,
            payload.get("result"),
            payload.get("outcome"),
            payload.get("guessState"),
            room,
            room.get("guessState") if room else None,
        ]
        for item in candidates:
            if not isinstance(item, dict):
                continue
            keys = {"correct", "winner", "actualIdentity", "identity", "peerGuess", "myGuess"}
            if any(key in item for key in keys):
                extracted = {
                    key: item[key]
                    for key in keys
                    if key in item and isinstance(item[key], (str, int, float, bool, type(None)))
                }
                # 服务端实际下发的是 actualType；actualIdentity 是本地推导字段
                if "actualIdentity" not in extracted and isinstance(item.get("actualType"), str):
                    extracted["actualIdentity"] = item["actualType"]
                # 结算原因（guess-timeout / both-locked 等）
                if isinstance(item.get("reason"), str):
                    extracted["reason"] = item["reason"]
                opponent = item.get("opponentGuess")
                if isinstance(opponent, dict) and isinstance(opponent.get("guess"), str):
                    extracted["opponentGuess"] = opponent["guess"]
                return extracted
        return None

    def _enrich_result(self, result: dict[str, Any] | None) -> dict[str, Any] | None:
        if not result:
            return result
        if "actualIdentity" not in result and isinstance(result.get("correct"), bool) and self._my_guess:
            result["actualIdentity"] = self._my_guess if result["correct"] else (
                "ai" if self._my_guess == "human" else "human"
            )
        return result

    def _start_opening_guard(self) -> None:
        if self._opening_guard_task and not self._opening_guard_task.done():
            return
        self._opening_guard_task = asyncio.create_task(
            self._opening_guard(), name="turing-first-message-guard"
        )

    async def _opening_guard(self) -> None:
        guard = max(1.0, self.config.opening_guard_sec)
        await asyncio.sleep(guard)
        if self._first_message_sent or self.state not in {GameState.ACTIVE, GameState.MATCHED}:
            return
        if self._first_message_deadline_ms and self._server_now_ms:
            remaining = (self._first_message_deadline_ms - self._server_now_ms) / 1000
            if remaining <= 0:
                return
        try:
            await self.send_message(self.config.opening_message)
            await self._publish({"event": "opening_guard_sent"})
        except TuringClientError as exc:
            await self._publish({"event": "opening_guard_error", "message": str(exc)})

    async def _publish(self, event: dict[str, Any]) -> None:
        self._event_seq += 1
        self._event_log.append((self._event_seq, event))
        async with self._condition:
            self._condition.notify_all()

    async def _shutdown_tasks(self) -> None:
        if self._stop_event:
            self._stop_event.set()
        current = asyncio.current_task()
        tasks = [task for task in (self._ws_task, self._opening_guard_task) if task and task is not current]
        self._ws_task = None
        self._opening_guard_task = None
        if self._ws is not None:
            try:
                await self._ws.close()
            except Exception:
                pass
        if tasks:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
        self._ws = None

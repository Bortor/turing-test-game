"""Public data models for the Turing game client."""

from __future__ import annotations

import os
import uuid
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - dotenv 为可选便利项
    load_dotenv = None

if load_dotenv is not None:
    # 支持仓库根目录 .env（自动向上查找）与启动目录 .env；已有环境变量优先
    load_dotenv()
    load_dotenv(Path.cwd() / ".env", override=False)


class GameState(StrEnum):
    IDLE = "idle"
    AUTHENTICATING = "authenticating"
    QUEUED = "queued"
    WAITING = "waiting"
    CALIBRATING = "calibrating"
    MATCHED = "matched"
    ACTIVE = "active"
    LOCKED_WAIT = "locked_wait"
    # 告别期（2026-08-02 服务端新增）：结算后房间 state=extended，
    # 双方可继续聊天（chatExtension.canSend），5 分钟后彻底关闭
    EXTENDED = "extended"
    RESULT = "result"
    CLOSED = "closed"
    ERROR = "error"


@dataclass(slots=True)
class GameConfig:
    """Runtime configuration loaded from environment variables.

    Passwords and tokens deliberately have no source-code defaults. The
    process that launches the client is responsible for supplying TT_PW.
    """

    base_url: str = "https://www.anyanygame.com"
    ws_url: str = "wss://www.anyanygame.com/api/turing/socket"
    username: str | None = None
    password: str | None = None
    nickname: str | None = None
    visitor_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    # Keep this aligned with the currently deployed web client.  The service
    # rejects stale fingerprints before it creates a matchmaking ticket.
    # 服务端更新版本后可能失效，可通过 TT_CLIENT_VERSION 覆盖为当前抓包值。
    # 2026-08-02 更新：服务端 serviceVersion b2f868e → 37a9c12（新增告别期/chatExtension）
    client_version: str = "37a9c12cd3cc7c9f35b1089960999b2f3f6ef035"
    protocol_version: int = 3
    chat_duration_sec: int = 600
    match_timeout_sec: int = 30
    allow_anonymous_chat_research: bool = False
    registered_privacy_notice_version: int = 1
    http_timeout_sec: float = 20.0
    ws_open_timeout_sec: float = 15.0
    ws_reconnect_max_sec: float = 30.0
    event_wait_default_sec: float = 20.0
    opening_message: str = "你好，刚连上，你等多久了？"
    opening_guard_sec: float = 12.0
    message_cooldown_sec: float = 2.5
    # 会话记录落盘目录（默认相对启动目录，可用 TT_SESSION_LOG_DIR 覆盖；
    # MCP 场景建议显式设置绝对路径或固定启动 cwd）
    session_log_dir: str = "sessions"

    @classmethod
    def from_env(cls) -> "GameConfig":
        """Build configuration from TT_* variables without logging secrets."""

        defaults = cls()

        def integer(name: str, default: int) -> int:
            raw = os.getenv(name)
            if not raw:
                return default
            try:
                return int(raw)
            except ValueError:
                return default

        def number(name: str, default: float) -> float:
            raw = os.getenv(name)
            if not raw:
                return default
            try:
                return float(raw)
            except ValueError:
                return default

        return cls(
            base_url=os.getenv("TT_BASE_URL", defaults.base_url).rstrip("/"),
            ws_url=os.getenv("TT_WS_URL", defaults.ws_url),
            username=os.getenv("TT_USERNAME") or os.getenv("TT_NICKNAME"),
            password=os.getenv("TT_PW") or os.getenv("TURING_PASSWORD"),
            nickname=os.getenv("TT_NICKNAME") or os.getenv("TT_USERNAME"),
            visitor_id=os.getenv("TT_VISITOR_ID") or str(uuid.uuid4()),
            client_version=os.getenv("TT_CLIENT_VERSION", defaults.client_version),
            protocol_version=integer("TT_PROTOCOL_VERSION", defaults.protocol_version),
            chat_duration_sec=integer("TT_CHAT_DURATION_SEC", defaults.chat_duration_sec),
            match_timeout_sec=integer("TT_MATCH_TIMEOUT_SEC", defaults.match_timeout_sec),
            allow_anonymous_chat_research=os.getenv("TT_ALLOW_RESEARCH", "0") == "1",
            registered_privacy_notice_version=integer(
                "TT_PRIVACY_NOTICE_VERSION", defaults.registered_privacy_notice_version
            ),
            http_timeout_sec=number("TT_HTTP_TIMEOUT_SEC", defaults.http_timeout_sec),
            ws_open_timeout_sec=number("TT_WS_OPEN_TIMEOUT_SEC", defaults.ws_open_timeout_sec),
            ws_reconnect_max_sec=number("TT_WS_RECONNECT_MAX_SEC", defaults.ws_reconnect_max_sec),
            event_wait_default_sec=number("TT_EVENT_WAIT_SEC", defaults.event_wait_default_sec),
            opening_message=os.getenv("TT_OPENING_MESSAGE", defaults.opening_message),
            opening_guard_sec=number("TT_OPENING_GUARD_SEC", defaults.opening_guard_sec),
            message_cooldown_sec=number("TT_MESSAGE_COOLDOWN_SEC", defaults.message_cooldown_sec),
            session_log_dir=os.getenv("TT_SESSION_LOG_DIR", defaults.session_log_dir),
        )

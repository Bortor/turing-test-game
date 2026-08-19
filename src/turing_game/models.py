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
    # 2026-08-04 更新：前端资产 index-7uw74jWv → index-BuoAOX_F，clientVersion → dddd5c42
    # 2026-08-05 更新：前端资产 index-BuoAOX_F → index-CkRu-209，clientVersion → 96a72363
    # 2026-08-05 14:32 更新：前端资产 index-CkRu-209 → index-CIenCRoJ，clientVersion → 8cb7adea
    # 2026-08-06 更新：前端资产 index-CkRu-209 → index-KZ7_3jXh，clientVersion → ddefd4eb
    # 2026-08-07 更新：前端资产 index-KZ7_3jXh → index-CX6W-B3M，clientVersion → fd41c0cd
    # 2026-08-09 更新：前端资产 index-CX6W-B3M → index-Cb0bc0Sy，clientVersion → a34a6e1d
    # 2026-08-10 更新：前端资产 index-Cb0bc0Sy → index-uckJV3wA，clientVersion → 2a5cca13
    # 2026-08-11 更新：前端资产 index-uckJV3wA → index-B-A_bZfd，clientVersion → ab69c7cc
    # 2026-08-12 更新：前端资产 index-B-A_bZfd → index-DWHZD6Gp，clientVersion → 588dc7a6
    # 2026-08-13 更新：前端资产 index-DWHZD6Gp → index-C9NdivmR，clientVersion → c6e81308
    # 2026-08-14 更新：前端资产 index-C9NdivmR → index-D3tP2GCZ，clientVersion → a9f7062a
    # 2026-08-17 更新：前端资产 index-D3tP2GCZ → index-CGe81UZ3，clientVersion → 97c108ac
    # 2026-08-18 更新：前端资产 index-CGe81UZ3 → index-Dyt-Xsxu，clientVersion → 75e224d5
    # 2026-08-19 更新：前端资产 index-Dyt-Xsxu → index-BC52yJE7，clientVersion → 881a1484
    client_version: str = "881a14843cee1ee11e09483ae3864bad92b634c5"
    protocol_version: int = 3
    chat_duration_sec: int = 600
    match_timeout_sec: int = 30
    allow_anonymous_chat_research: bool = False
    # 2026-08-04 前端新增：趣味匹配开关（"打开我超牛的对手将优先匹配在一起"），
    # 随 start 请求体下发；默认关闭，协议无关，仅匹配偏好
    fun_match_enabled: bool = False
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
            fun_match_enabled=os.getenv("TT_FUN_MATCH_ENABLED", "0") == "1",
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

---
name: turing-test-game
description: '通过 turing-test-game MCP 工具进行一局 AnyAnyGame 图灵测试。'
category: games
---

# Turing Test Game

本 skill 描述 turing-test-game MCP 服务器的工具操作方式。HTTP 认证、
WebSocket、重连、消息去重与倒计时均由 MCP 服务器（协议客户端）负责，
正常流程不需要浏览器自动化或 shell 脚本。

## 启动流程

1. 确认依赖已安装（`mcp`、`websockets`），并设置环境变量：
   - `TT_USERNAME` 或 `TT_NICKNAME`：用户名/昵称（至少一个）
   - `TT_PW`：密码
2. 以 stdio 方式启动 MCP 服务器：
   `python mcp_server/turing_mcp_server.py`
3. 通过 MCP 工具进行一局游戏；一局结束后如需再开新局，需用户明确要求。

## MCP 工具列表

| 工具 | 说明 |
|------|------|
| `turing_start_match` | 登录并开始一局匹配；会话非空闲/结束状态时不要重复调用 |
| `turing_wait_event` | 等待队列、匹配、聊天、锁定、重连或结算事件 |
| `turing_send_message` | 向当前对手发送一条聊天消息 |
| `turing_get_state` | 获取当前安全状态、消息、倒计时与结果 |
| `turing_submit_guess` | 提交 `human` 或 `ai` 判定（不可撤回） |
| `turing_leave` | 离开当前对局并结束会话 |
| `meme_search` | 在本地梗知识库中检索网络流行语/梗 |

每次操作后调用 `turing_wait_event` 等待事件；在 `result`、`closed`、`error`
状态下停止调用对局工具。

## 数据落盘位置

- 对局会话记录：`$TT_SESSION_LOG_DIR`（默认 `sessions/`，相对启动目录）
- 梗知识库：`scripts/data/memes.json`（由 `scripts/build_kb.py` 生成，不随仓库分发）

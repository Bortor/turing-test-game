# AGENTS.md

本仓库是「通用图灵测试 Agent 工具链」：协议客户端、stdio MCP 集成、
萌娘百科梗知识库构建与检索工具、协议逆向文档、离线测试。
**不含对局策略与实战记录**，请勿新增或回填此类内容。

## 目录

- `src/turing_game/`：协议客户端（`client.py` 为 HTTP/WebSocket 协议逻辑与状态机）
- `mcp_server/turing_mcp_server.py`：stdio MCP 适配层，暴露 7 个工具
- `scripts/`：`build_kb.py`（萌娘百科爬取）、`search_kb.py`（BM25 检索）、
  `live_validation.py`（单局协议验证）
- `reverse/`：协议逆向文档与诊断脚本
- `hermes_skill/turing-test-game/`：Agent skill（仅工具操作说明）
- `tests/`：离线协议回放测试

## 前置条件

- Python 3.11+
- 可访问 GitHub 与 PyPI 的网络（国内网络可能需要代理或镜像源）
- 凭据：`TT_USERNAME` / `TT_NICKNAME`（至少一个）与 `TT_PW`；
  无凭据时可以完成安装与离线测试，但无法进行真实对局
- 账号：需先在 anyanygame.com 的图灵测试页面注册（本仓库不提供注册接口，
  且客户端不支持游客模式）；公开演示请使用与真实身份无关的临时账号

## 安装与测试

```powershell
# Windows (PowerShell)
python -m pip install -e .
$env:PYTHONPATH = "src"
python -m unittest discover -s tests -v
```

```bash
# macOS / Linux
python -m pip install -e .
PYTHONPATH=src python -m unittest discover -s tests -v
```

## 验证安装

```powershell
python -c "from turing_game.client import TuringClient; print(TuringClient().snapshot()['state'])"
turing-game state
```

## 运行

- 环境变量：`TT_USERNAME` / `TT_NICKNAME`（至少一个）与 `TT_PW`（必填）；
  可选变量见 `src/turing_game/models.py` 与 `.env.example`。
- MCP 服务器：`python mcp_server/turing_mcp_server.py`（stdio）。
- 梗库构建：`python scripts/build_kb.py`（可选 `--merge FILE` 合并外部笔记）；
  检索：`python scripts/search_kb.py <关键词>`。

## AGENTS.md 约定说明

Codex 等 Agent 会在打开仓库时自动读取本文件。若宿主 Agent 不支持该约定
（例如部分 Hermes 配置），请将本文件内容作为上下文提供给 Agent 后再安装。

## 修改边界

- 不得修改 `src/turing_game/client.py` 的协议逻辑与
  `mcp_server/turing_mcp_server.py` 的 MCP 工具逻辑。
- 不得提交：`log.md`、`memes.md`、`sessions/`、`scripts/data/`、
  `reverse/cookies.txt`、`*.pyc`、`__pycache__`、`.env`。
- 不得引入硬编码账号、对局策略、实战记录或原网站前端源码；文档使用中文。
- 对局会话记录与知识库数据属于本地运行时数据，不入库、不纳入版本控制。

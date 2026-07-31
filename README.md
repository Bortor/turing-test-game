# Turing Test Game — 通用图灵测试 Agent 工具链

一套可复用的「图灵测试」Agent 工具链：通过 HTTP + WebSocket 协议客户端与
AnyAnyGame 图灵测试服务交互，并以 MCP（stdio）方式集成到 Agent 中。
项目只包含通用工具，不含任何对局策略或实战记录。

## 项目定位

公开内容包括：

- 协议客户端：`src/turing_game/`（登录、匹配、WebSocket 消息、判定提交）
- MCP 集成：`mcp_server/`（stdio 适配层，把客户端暴露为 MCP 工具）
- 梗知识库构建工具：`scripts/build_kb.py`（爬取萌娘百科）与
  `scripts/search_kb.py`（零依赖 BM25 检索）
- 协议逆向文档与诊断脚本：`reverse/`
- 离线协议回放测试：`tests/`

不包含：对局策略、实战记录、原网站前端源码。

## 架构

| 层 | 位置 | 职责 |
|----|------|------|
| 客户端 | `src/turing_game/` | 协议逻辑：认证、WebSocket、状态机、重连、会话落盘 |
| MCP 服务器 | `mcp_server/turing_mcp_server.py` | stdio 适配层，暴露 7 个工具 |
| 梗知识库 | `scripts/` | 萌娘百科爬取 + BM25 检索 |
| 逆向文档 | `reverse/` | 协议抓包与逆向分析文档、诊断脚本 |
| Skill | `hermes_skill/turing-test-game/` | Agent 使用 MCP 工具的操作说明 |

客户端是唯一持有协议逻辑的组件，MCP 适配层不包含协议逻辑，便于替换运行环境。

## 快速开始

### 账号注册

使用客户端前，需要先在 AnyAnyGame 的图灵测试页面注册账号：本项目只提供
登录与对局能力，不包含注册接口，注册入口与规则以网站当前流程为准。

- 客户端仅支持已注册账号登录，不支持游客/匿名模式（游客模式需要 altcha
  安全验证，不在本客户端范围内）。
- 游客账号通常有对局次数限制（站点配置 `guestMatchLimit`），建议直接使用
  已注册账号。
- 公开演示或视频请使用与个人真实身份无关的临时账号；密码只通过 `TT_PW`
  环境变量注入，不要写入任何会被提交的文件。

### 环境变量

| 变量 | 必填 | 说明 |
|------|------|------|
| `TT_USERNAME` | 二选一 | 用户名 |
| `TT_NICKNAME` | 二选一 | 昵称（未设置时回退为用户名） |
| `TT_PW` | 是 | 密码 |

可选变量（默认值见 `src/turing_game/models.py`）：`TT_BASE_URL`、
`TT_WS_URL`、`TT_SESSION_LOG_DIR`、`TT_OPENING_MESSAGE`、
`TT_VISITOR_ID` 等。

### 安装

```powershell
python -m pip install -e .
```

> 已实测：全新 `git clone` 后执行 `python -m pip install -e .` 即可安装，
> `turing-game state` 与离线测试（5/5）可直接运行。把仓库地址交给 Agent 时，
> Codex 等支持 `AGENTS.md` 约定的 Agent 会自动读取仓库内指引；若你的 Agent
> 平台不读取该文件（如部分 Hermes 配置），把 `AGENTS.md` 内容作为上下文提供
> 即可。前置条件：Python 3.11+、可访问 GitHub/PyPI 的网络（国内建议配置代理
> 或镜像）、以及 `TT_USERNAME`/`TT_NICKNAME`/`TT_PW` 凭据（无凭据只能跑
> 离线测试）。

### 命令行

```powershell
$env:TT_USERNAME = "your-username"
$env:TT_PW = "your-password"
turing-game start
```

### MCP 注册

以 stdio 方式启动服务器：

```powershell
python mcp_server/turing_mcp_server.py
```

在 MCP 客户端配置中注册（`command` 按实际 Python 环境调整）：

```json
{
  "mcpServers": {
    "turing-test-game": {
      "command": "python",
      "args": ["mcp_server/turing_mcp_server.py"],
      "env": {
        "TT_USERNAME": "your-username",
        "TT_NICKNAME": "your-nickname",
        "TT_PW": "your-password"
      }
    }
  }
}
```

### Skill 安装

将 `hermes_skill/turing-test-game/` 复制到 Agent 的 skills 目录
（如 `~/.codex/skills/` 或 Hermes 的 `skills/`）。Skill 内容仅描述
MCP 工具的操作方式，不含对局策略。

## 梗知识库

构建（爬取萌娘百科，写入 `scripts/data/memes.json`，该目录不随仓库分发）：

```powershell
python scripts/build_kb.py
```

可选：合并一份外部 Markdown 笔记（`## 关键词` + 正文格式）：

```powershell
python scripts/build_kb.py --merge path/to/notes.md
```

检索：

```powershell
python scripts/search_kb.py 绷不住
```

MCP 环境下可用 `meme_search` 工具检索同一份知识库。

## 目录结构

```
turing-test-game/
├── src/turing_game/          # 协议客户端
│   ├── client.py             # HTTP/WebSocket 协议逻辑与状态机
│   ├── models.py             # 数据模型与 TT_* 环境变量
│   └── cli.py                # 诊断用命令行
├── mcp_server/               # stdio MCP 适配层
├── scripts/                  # 梗知识库构建与检索工具
├── reverse/                  # 协议逆向文档与诊断脚本
├── hermes_skill/             # Agent skill（工具操作说明）
├── tests/                    # 离线协议回放测试
└── pyproject.toml
```

## 测试

```powershell
$env:PYTHONPATH = "src"
python -m unittest discover -s tests -v
```

## 数据与隐私

- 对局会话记录默认写入启动目录下的 `sessions/`，可用 `TT_SESSION_LOG_DIR`
  覆盖；`sessions/` 与 `scripts/data/` 均已通过 `.gitignore` 排除。
- 凭据只通过环境变量注入，客户端不在公开快照中返回密码、JWT、cookie 等
  敏感信息。

## 免责声明

本项目仅用于协议学习与互操作研究，不提供任何对局策略。使用本项目访问
第三方服务时，请自行遵守目标网站的服务条款、适用法律与平台规则；因使用
本项目产生的任何后果由使用者自行承担。

## 许可

MIT，见 [LICENSE](LICENSE)。

# 图灵测试站点逆向工程文档（reverse engineering）

> 目标：让接手者不打开网页也能开发出对应工具
> 抓取时间：2026-07-31 11:15
> 站点：https://www.anyanygame.com/turing-test

## 1. 架构总览

- **纯 HTTP 轮询架构**，无 WebSocket（performance API 无 ws 资源）
- 前端 React（受控组件），主包 index-BqIvqv6K.js（168KB gzip，571KB 源码，混淆压缩）
- 图灵专用包 index-C5-BVGFS.js（22KB，实际是 pbkdf2/base64 工具库，用于密码哈希）
- API 基础路径：`/api/turing${n}`（模板拼接，n 为端点名）
- 消息实时性通过轮询 `/api/turing/socket` 实现（端点存在，需确认轮询间隔）

## 2. API 端点清单

| 端点 | 方法 | 用途 | 观测响应大小 |
|------|------|------|-------------|
| /api/analytics/visit | GET | 访问统计 | 300B |
| /api/auth/account-access | GET | 账户访问检查 | 376B |
| /api/turing/guest-security-challenge?verificationClient=dual | GET | 访客安全挑战（altcha 验证） | 680B |
| /api/turing/start | POST | 开始匹配/排队 | 752-1258B |
| /api/turing/socket | ? | 消息轮询（实时通信） | ? |
| /api/turing/leave | ? | 离开房间 | ? |
| /api/turing/settings | ? | 设置 | ? |
| /api/turing/rooms/{roomId}/guess | POST | 提交判定（H/A） | 552-674B |
| /api/auth/turing-login | POST | 登录 | 732B |

## 3. 关键发现：房间 ID = 对手 ID

```
room_XXXXXXXXXXXX → 对手 XXXX
room_YYYYYYYYYYYY → 对手 YYYY
room_ZZZZZZZZZZZZ → 对手 ZZZZ
```
模式：`room_` + 随机前缀 + 对手ID。房间 ID 包含对手 ID，可反推。

## 4. localStorage 数据结构

```json
{
  "token": "eyJhbG... (JWT，截断)",
  "anyanygame.turing.stats": "{\"games\":N,\"correct\":M}",
  "anyanygame.turing.player": "{\"playerId\":\"T-XXXX\",\"nickname\":\"<username>\",\"access\":{\"registered\":true,\"identity\":{\"complete\":false,\"verificationStatus\":\"missing\",\"hasPhone\":false,\"legalVersion\":null},\"guestMatchLimit\":1,\"guestMatc...",
  "turing_compliance_v3": "1700000000000",
  "user": "{\"id\":<user_id>,\"username\":\"<username>\",\"avatar_url\":null,\"is_admin\":0,\"accountScope\":\"turing\",\"turingIdentity\":{\"complete\":false,\"verificationStatus\":\"missing\",\"hasPhone\":false,\"legalVersion\":null}}",
  "generation_tasks_v1": "[]",
  "anyanygame.turing.registered-privacy-notice": "{\"<user_id>\":{\"version\":1,\"acknowledged\":true,\"allowAnonymousChatResearch\":false}}",
  "anyanygame.turing.security-calibration.v1": "eyJ2Ij... (base64)",
  "anyanygame.accountAccess": "{\"registrationEnabled\":true,\"guestMatchLimit\":1,\"verificationMode\":\"altcha\",\"fetchedAt\":1700000000000}",
  "anyanygame.visitorId": "00000000-0000-0000-0000-000000000000"
}
```

关键字段：
- `playerId` 格式：`T-XXXXXXX`（8位随机，如 T-XXXXXXX）
- 验证方案：altcha（guest-security-challenge）
- 游客匹配上限：1 局（guestMatchLimit=1）
- stats 结构：{games, correct}（本机战绩，跨会话持久）

## 5. 游戏状态机（页面文本特征 → 状态）

| 状态 | body.innerText 特征 | 触发 |
|------|---------------------|------|
| HOME | "屏幕那边， 是人吗？" + "开始匹配" | 初始 |
| PRIVACY_DIALOG | "使用须知" + "确认并开始匹配" | 点开始匹配（未同意过） |
| LOGIN_DIALOG | "登录后继续" | 游客次数用完/需登录 |
| REGISTER_DIALOG | "创建安全账号" | 无账号 |
| QUEUE | "您正在排队" + "前方 N 位玩家" | 确认匹配 |
| CALIBRATING | "正在校准" + progressbar | 队列到头 |
| MATCHED | "CONNECTED WITH" + "TIME LEFT" | 匹配成功 |
| LOCKED_WAIT | "ANSWER LOCKED" + "等待对方判定 · Ns" | 我方锁定后 |
| RESULT | "ROUND COMPLETE" | 结算 |
| DISCONNECTED | "对方已中途断开" | 对方断开 |

## 6. 游戏规则（观测确认）

- 开局 60 秒内必须发言，否则判负（"首分钟未发言"）
- 匹配后"TIME LEFT"从 10:00 倒计时（10分钟上限）
- 锁定按钮匹配后 5 秒解锁（"H 5s 后解锁"）
- 一方锁定后，另一方 45 秒反判窗口
- 双方锁定 → 立即结算
- 判定选项：H（真人）/ A（AI），锁定不可更改

## 7. 前端关键实现细节

### React 受控组件事件注入
- 开始匹配按钮真实 handler 在 `__reactProps$xxx.onClick`（DOM onclick 属性是空壳 `function qt(){}`）
- 聊天输入框用 `__reactProps$xxx.onChange({target:{value}})` 直接注入
- 昵称输入框同理（原生 setter + dispatch input/change 也可）

### 结算文案
- "判断正确" / "判断错误" + "对方是真人玩家/AI 机器人"
- "TA 认为你是AI/真人"
- "本机记录 X / Y" + "Z%"（本机战绩，与 localStorage stats 一致）

### 对手 ID 格式
- UNKNOWN_XXXX（4位随机大写字母数字，如 UNKNOWN_ABCD）

## 8. 待补抓信息

- [x] /api/turing/socket 的请求方法、参数、响应格式（关键：消息轮询）→ 静态分析完成（见上 WS 协议）
- [x] /api/turing/start 的请求体结构 → 实测抓包完成
- [x] /api/turing/rooms/{id}/guess 的请求体结构 → 静态分析 {sessionId, guess}
- [ ] 发消息的端点 → 静态分析为 WS message.send
- [ ] 消息轮询间隔 → 需运行时确认
- [ ] JWT token 完整结构（payload claims）→ 需解码
- [ ] altcha 验证流程 → 部分（guest-security-challenge 端点）
- [ ] 排队位置更新的轮询方式 → 疑似 WS match.update / 轮询

## 10. WS 运行时抓包（2026-07-31 11:22 部署）

已注入 WebSocket hook（window.__wsCaptured），等待下一局匹配后验证。
注意：hook 在匹配后注入可能错过已建立的 WS 连接——需要在页面加载前注入（或从 /api/turing/socket 端点重新连接）。

## 11. 前端源码分析（原件已删除，不随仓库分发）

浏览器主包与图灵专用工具包属于网站前端源码，涉及版权，本仓库不保留原件，
仅保留分析结论：

- index-main.js（571KB 混淆主包，含全部游戏逻辑）
- index-turing.js（60KB，实际是 pbkdf2/base64 工具库）
- pbkdf2.js（99B 引导）

分析结论：
- 主包内有完整 WS 协议：match.subscribe/room.subscribe/message.send
- React 事件注入点：__reactProps 键
- 端点全部模板拼接：`/api/turing${n}`

## 12. 纯 API 客户端验证（2026-07-31 11:42 实测成功！）

**结论：已登录用户可以完全绕过浏览器和 altcha，纯 HTTP+WS 玩图灵测试。**

### 完整流程（实测通过）

```
① POST /api/auth/turing-login
   body: {"identifier":"<username>","password":"<明文密码>"}
   headers: 无需特殊（连 X-Visitor-Id 都不需要）
   → 200 {"token":"eyJ...","user":{...}}
   token: JWT HS256, payload {id, username, is_admin, auth_version, iat, exp}
   有效期: 7天 (exp-iat = 604800)

② POST /api/turing/start
   headers: Authorization: Bearer <token>, X-Visitor-Id: <任意UUID>
   body: {"nickname":"<username>","protocolVersion":3,
          "clientVersion":"0000000000000000000000000000000000000000",
          "chatDurationSec":600,"matchTimeoutSec":30,
          "allowAnonymousChatResearch":false,"registeredPrivacyNoticeVersion":1}
   → 202 {
       "player": {"playerId":"T-XXXX","nickname":"<username>","access":{...}},
       "ticket": {"ticketId":"ticket_XXXXXXXXXX","sessionId":"session_XXXXXXXXXX",
                  "status":"queued","access":{...},"queuePosition":N,
                  "queuedAt":...,"retryAfterMs":5000},
       "config": {"debugEnabled":false,"protocolVersion":3,
                  "serviceVersion":"0000000000000000000000000000000000000000",
                  "registrationEnabled":true,"guestMatchLimit":1,
                  "verificationMode":"altcha"},
       "securityCalibrationToken":""
     }

③ 连接 WS: wss://www.anyanygame.com/api/turing/socket
   发: {"type":"match.subscribe","requestId":"<uuid>","ticketId":"<ticketId>","sessionId":"<sessionId>"}
   收: {"type":"match.subscribed","requestId":"<uuid>","ok":true/false,
        "statusCode":200/410,"code":"...","error":"..."}
   错误示例: {"type":"match.subscribed","requestId":"test-1","ok":false,
              "statusCode":410,"code":"match_ticket_expired","error":"匹配凭证已失效"}

④ 排队中：match.update 推送（status 字段变化，从 queued → calibrating → matched）
⑤ 匹配成功：match.update 带 roomId → 发 room.subscribe
⑥ 聊天：message.send / 收 room.update
⑦ 判定：POST /api/turing/rooms/{roomId}/guess  body: {"sessionId":"...","guess":"human"/"ai"}
```

### 关键认证细节
- **已登录用户跳过 altcha**（start 请求里 `...ue?{}:{...Re,securityCalibrationToken:Le}`——登录时 ue 为真，不带 challenge）
- 登录接口不需要 X-Visitor-Id（实测）
- start 必须带 X-Visitor-Id（缺了报 400 "缺少访客标识"）
- visitorId 是客户端生成的 UUID（无需服务端注册）
- curl 失败的原因：git-bash 中文 JSON 编码问题 → 用 Python urllib 成功
- WS 连接不需要 token 参数（浏览器 API 不能加 header，服务端接受裸连接，认证靠消息内的 ticket/session）

### 待验证（排队中行为）
- [x] match.update 的完整推送结构（queued→matched 的状态变化）
- [x] 排队轮询：WS 实时推送（约 12 秒一条），非定时轮询
- [~] guess 的实际响应结构：错误格式已抓（410 turing_room_gone），成功响应未抓（需真实对局中测）

### guess 错误格式（实测）
```
POST /api/turing/rooms/{roomId}/guess  body: {"sessionId":"...","guess":"human"}
房间过期 → 410 {"code":"turing_room_gone","error":"聊天房间不存在或已过期"}
```

### 排队状态机（实测 2026-07-31 11:45）

```
POST /api/turing/start
  → ticket.status = "queued", queuePosition=N, retryAfterMs=5000

WS match.subscribe 后，服务端推送 match.update 序列：
  ① {"type":"match.update","ticketId":"ticket_XXXXXXXXXX",
     "status":{"status":"queued","queuePosition":N,"queuedAt":...,"queuedForMs":...,
               "retryAfterMs":5000,"serverNow":...}}
     → queuePosition 递减（约12秒一条）

  ② {"status":{"status":"waiting","waitedMs":4,"timeoutMs":30000,"serverNow":...}}
     → 匹配窗口期（30秒超时）

  ③ {"status":{"status":"matched","roomId":"room_XXXXXXXXXXXX",
     "endsAt":...,"guessUnlocksAt":...,"serverNow":...}}
     → 匹配成功！roomId = room_ + 随机 + 对手ID
```

### 完整时序（实测数据）
- 排队耗时：~N 秒（从排队到 matched）
- queued 推送间隔：~12秒
- waiting → matched：~6秒
- endsAt = matched 时间 + 600秒（10分钟房间上限）
- guessUnlocksAt = matched + 10秒（与页面 "H 10s 后解锁" 一致）

## 9. 抓包工具（已部署）

在浏览器控制台注入了 fetch 拦截器：
```js
window.__captured // 数组，记录 {t, url, method, body}
window.__fetchHooked // 标志位
```
后续匹配/聊天时自动记录所有 /api/ 请求。读取：`JSON.stringify(window.__captured)`

## 13. 客户端核心线上验证（2026-07-31）

已用新的 Python HTTP + WebSocket 客户端完成一次完整单局验证：

- 登录、创建匹配票据、WebSocket `match.subscribe` 均成功
- 排队状态按 `queued → waiting → matched` 推送
- `room.subscribe` 成功并收到系统消息
- 首条消息通过 `message.send` / `message.ack` 成功发送
- 服务端会拒绝过快的连续消息；客户端现已加入 2.5 秒本地发送冷却
- 判定解锁时间约为匹配后 10 秒，客户端在解锁前将 `can_guess` 置为 false
- 提交 `human` 判定成功，服务端推送 45 秒反判窗口结束消息
- 最终 `room.update` 返回 `state: result` 和 `result.correct: true`
- 当服务端只返回 `correct` 时，客户端根据已提交 guess 推导 `actualIdentity`
- 本局结束后没有自动启动下一局

验证过程中对手仅发送简短问候，脚本在锁定后未继续发言；该行为符合房间已锁定后的状态机约束。

## 14. 生态观察日志

### 2026-08-04：作者 vlog「服务器持续断连，真相浮出水面！part1」

- 触发源：作者 B 站动态（龙皮皮ACG, UID 17598723）08-01 发布开发日记 vlog，
  承接 07-27「图灵测试目前服务异常。正在检修中」动态，属运维性质记录。
- 前端资产：index.html 仍引用 `index-7uw74jWv.js` + `index-C49qFdOm.css`，
  与 watch 基线一致 → 无新 JS/CSS，协议面无改动迹象。
- 客户端现状（已覆盖，无需改动）：
  - WS 带 `ping_interval=20 / ping_timeout=20` 心跳；
  - 断线指数退避重连（1s 起，上限 `ws_reconnect_max_sec`）；
  - 重连后 `_subscribe_current` 自动补 `room.subscribe`（带 afterSequence 增量续订）。
- 结论：该动态不构成协议变更；若服务器断连持续，注意观察 WS 断连是否伴随
  `match_ticket_expired`（410），以及重连后房间是否仍有效（room gone 时
  wait_event 会收到 result/error，客户端已按状态机处理）。

### 2026-08-04 12:00：前端资产更新（watch 触发适配）

- 前端资产变化：`index-7uw74jWv.js` + `index-C49qFdOm.css`
  → `index-BuoAOX_F.js` + `index-DgNc1rWb.css`（Vite 重新构建）。
- **clientVersion 更新**：`37a9c12cd3cc7c9f35b1089960999b2f3f6ef035`
  → `dddd5c42198a853910e506cf02c0abe18f29704c`。
  客户端 `models.py` 默认值已同步（可被 TT_CLIENT_VERSION 覆盖）。
  若 start 返回 `turing_client_outdated` 说明版本又变了，需重新抓包。
- **新增错误码 `turing_phone_verification_required`**：start 匹配时服务端可能返回，
  表示账号需完成手机号验证才能匹配。前端行为：从 `payload.access` 更新本地 access
  数据并提示「当前手机号验证服务暂不可用，请稍后再试」（或服务端 message）。
  已注册且已验证账号理论上不受影响；未验证账号 start 会被拒。
- **注册/登录流程新增手机验证字段**（仅前端 UI，协议客户端不涉及）：
  `phone / smsCode / smsSessionId / bindPhone / bindSmsCode / bindSmsSessionId`，
  短信验证码流程（CSS 类 `turing-auth-phone`、`turing-auth-sms-row` 等）。
- **WS 消息类型无变化**：match.*（subscribe/subscribed/update/fatal/unsubscribe）、
  room.*（subscribe/subscribed/update/fatal/superseded/unsubscribe）、
  message.send/ack 全部与旧版一致。端点无变化（`/api/turing${l}` 模板 + socket）。
- 管理面板 chunk 更新（admin 专属，不影响协议客户端）：
  `TuringAdminPanel-oRv5s0WF.js` → `TuringAdminPanel-BJUBZ-bZ.js`、
  `WeirdChatAdminPanel-CeMJHSvs.js` → `WeirdChatAdminPanel-WPAv6J3o.js`。
- UI 新增：广告位（`turing-ad-slot`，debug 模式 `is-debug` 占位）、
  消息举报（`/rooms/{id}/messages/{msgId}/report` POST，旧版已有未记录）、
  结算后导出图片/回顾（`turing-result-export-image`、`turing-post-game-review-actions`）、
  设置面板（`turing-settings`）。
- 适配动作：仅更新 `client_version` 默认值（src/turing_game/models.py），
  无协议机制变化 → 未改 WS/状态机代码。手机验证门槛若开始影响已注册账号，
  需观察 start 是否返回新错误码（客户端会以 TuringClientError(code=...) 冒泡）。

### 2026-08-04 12:30：补充发现 `funMatchEnabled`（上一轮遗漏）

- **start 请求体新增字段 `funMatchEnabled`**（bool，默认 false）：旧版
  `index-7uw74jWv` 中完全不存在，新版 `index-BuoAOX_F` 随
  `{nickname, protocolVersion, clientVersion, chatDurationSec, matchTimeoutSec, ...}`
  一并下发。语义：趣味匹配开关（设置 UI 文案「打开我超牛的对手将优先匹配
  在一起」），仅匹配偏好，不影响协议状态机。
- 适配：`src/turing_game/models.py` 新增 `fun_match_enabled` 配置
  （`TT_FUN_MATCH_ENABLED=1` 开启），`client.py` start body 带
  `"funMatchEnabled": false` 默认值，与前端默认一致。
- 服务端对缺失字段的行为未实测（离线分析推断为宽松解析，不传等同 false）；
  若 start 因此报错（如 400），以抓包为准回退该字段。

### 2026-08-05 12:00：前端资产更新（watch 触发适配）

- 前端资产变化：`index-BuoAOX_F.js` + `index-DgNc1rWb.css`
  → `index-CkRu-209.js` + `index-D4lbjuix.css`（Vite 重新构建，体积 +14KB JS）。
- **clientVersion 更新**：`dddd5c42198a853910e506cf02c0abe18f29704c`
  → `96a72363a680a96076e8c8812745d92c7f326f26`。
  客户端 `models.py` 默认值已同步（可被 TT_CLIENT_VERSION 覆盖）。

### 2026-08-05 14:32：前端资产再次更新（同日第二次）

- 前端资产变化：`index-CkRu-209.js` → `index-CIenCRoJ.js`（`?v=8cb7adea5879`）。
- **clientVersion 更新**：`96a72363a680a96076e8c8812745d92c7f326f26`
  → `8cb7adea5879fca01fe22f4026a5f6266bda2985`。
  客户端 `models.py` 默认值已同步；config.yaml `TT_CLIENT_VERSION` 同步更新
  （旧值 37a9c12 为 08-02 遗留，env 覆盖优先级高于 models.py 默认值，
  若只改仓库不改 config 会继续被拒，需重启 Hermes 使 MCP server 重新注入 env）。
- **新增错误码（start 匹配阶段）**：
  - `turing_match_verification_required` / `turing_match_verification_failed`：
    安全校准（匹配验证）不满足。前端行为：提示「安全校准已更新，请再次点击
    开始匹配」，重置到 intro 页并设置重新校准 flag（`zn(!0)`），下次 start 会
    重新走校准流程。协议客户端遇到这两个 code 属预期重试场景：重新调 start
    即可（calibrating 状态由 WS match.update 驱动）。
  - 旧错误码 `turing_security_calibration_required` / `turing_security_calibration_failed`
    保留，与 match_verification_* 走同一 catch 分支（本次补记，旧版已有）。
  - `turing_account_required`（本次补记，旧版已有）：游客账号匹配受限，
    `payload.access.guestMatchLimit` 更新剩余次数，`access.registrationRequired`
    为 true 时需注册。已注册账号不受影响。
  - `turing_phone_verification_required` 保留：`payload.access` 更新本地 access，
    需完成手机号验证（「因为网站出现异常事件，临时开启手机注册验证」）。
- **补记 securityRequirement 机制（旧版已有，08-04 轮漏记）**：
  room.update 可携带 `securityRequirement` 字段，值域 `"registration"` /
  `"phone_verification"`：
  - `registration`：你的首次发言被举报，需注册或登录后再继续
    （前端提示「你的首次发言被举报，请注册或登录后再继续。」）；
  - `phone_verification`：需先完成手机号验证（「为保护聊天环境，请先完成
    手机号验证后再继续。」）。
  语义：服务端在聊天过程中下发安全门槛，前端检测到值变化后暂停聊天并弹出
  验证 UI（CSS 类 `turing-emergency-security`）。对协议客户端：房间对象多一
  个字段，宽容解析不受影响；但发送消息可能被服务端拒绝，若 room.update 带
  该字段应停止发送并报告。**尚未实测触发条件**，仅离线记录。
- **start 请求体完整字段**（本次核对旧版一致，08-04 轮未记全）：
  `nickname / protocolVersion / clientVersion / chatDurationSec /
  matchTimeoutSec / funMatchEnabled / allowAnonymousChatResearch /
  registeredPrivacyNoticeVersion`，debug 模式追加 `debugParams`。
  `allowAnonymousChatResearch`（匿名聊天研究同意，默认 false）与
  `registeredPrivacyNoticeVersion`（隐私通知版本）客户端已支持
  （TT_ALLOW_RESEARCH / TT_PRIVACY_NOTICE_VERSION），无需改动。
- **无协议机制变化**：WS 消息类型（match.*/room.*/message.send+ack）、
  端点模板（`/api/turing${l}`→`${n}` 仅为 minified 变量名）、
  guess 提交 body `{sessionId, guess}`、chatExtension 字段集全部与旧版一致。
  `holdSettlement`/`deferredSettlement` 是前端本地结算动画状态，不上送协议。
- UI 新增（CSS +7 类，均不影响协议）：`turing-emergency-security`（安全门槛
  弹层）、`turing-generate-image-button`（结算后生成聊天长图）、
  `turing-result-share-icon-button`（结果分享）、`turing-review-result-button`
  （结果回顾）。
- 适配动作：仅更新 `client_version` 默认值（src/turing_game/models.py）。
  新错误码/securityRequirement 机制无需代码改动（错误码原样冒泡、
  房间字段宽容解析）；若实际对局中 start 返回 match_verification_* 或
  room.update 带 securityRequirement，需抓包记录触发条件后决定是否硬编码处理。

### 2026-08-06 12:00：前端资产更新（watch 触发适配）

- 前端资产变化：`index-CkRu-209.js` → `index-KZ7_3jXh.js`（Vite 重新构建，
  体积 +1.3KB：635,894 → 637,162 bytes）。
- **clientVersion 更新**：`8cb7adea5879fca01fe22f4026a5f6266bda2985`
  → `ddefd4ebd35e3d1787479efa109e257383890ffa`。
  客户端 `models.py` 默认值已同步（可被 TT_CLIENT_VERSION 覆盖）。
- **协议面零变化**（新旧 JS 全量对比确认）：
  - WS 消息类型 13 种完全一致（match.subscribe/subscribed/update/fatal/
    unsubscribe、room.subscribe/subscribed/update/fatal/superseded/
    unsubscribe、message.send/ack）；
  - 错误码集合 13 个完全一致（turing_account_required 等）；
  - start 请求体字段 9 个完全一致（nickname/protocolVersion/clientVersion/
    chatDurationSec/matchTimeoutSec/funMatchEnabled/allowAnonymousChatResearch/
    registeredPrivacyNoticeVersion/debugParams）；
  - chatExtension/告别期字段集完全一致（availableUntil/inviteEndsAt/
    startedAt/endsAt/requestedAt/pending/canSend/reviewOnly/selfReturned/
    opponentDeparted/finished）。
- **新增页面级维护模式检测（仅前端 UI，不影响协议）**：
  前端每 15s 轮询 `GET /maintenance`（visibilitychange 时立即查一次），
  响应 `{active: true, message: "..."}` 时渲染全屏维护弹窗
  （`turing-maintenance-backdrop` + `SERVER MAINTENANCE` 标记，默认文案
  「网站维护中，请稍后访问。」）；请求失败或 `active !== true` 时清除弹窗。
  2026-08-06 实测：直接 curl `/maintenance` 返回 SPA index.html（非 JSON），
  说明该端点平时不存在（走 SPA fallback）或仅在维护窗口期启用；前端 catch
  静默处理。协议客户端无需轮询该端点；若维护期间 start 被服务端拒绝，
  以返回的错误码/HTTP 状态为准（观察项，未实测）。
- 适配动作：仅更新 `client_version` 默认值（src/turing_game/models.py），
  无协议机制变化 → 未改 WS/状态机代码。

### 2026-08-07 12:00：前端资产更新（watch 触发适配）

- 前端资产变化：`index-KZ7_3jXh.js` + `index-D4lbjuix.css`
  → `index-CX6W-B3M.js` + `index-D5iVH8o3.css`（Vite 重新构建，JS +3.6KB：637,162
  → 640,768 bytes；CSS 145,669 bytes）。
- **clientVersion 更新**：`ddefd4ebd35e3d1787479efa109e257383890ffa`
  → `fd41c0cd17233dc464c8df990400a43d90bc08ed`。
  客户端 `models.py` 默认值已同步（可被 TT_CLIENT_VERSION 覆盖）。
- **协议面保持项**（新旧全量特征对比确认）：
  - WS 消息类型 13 种完全一致（match.subscribe/subscribed/update/fatal/
    unsubscribe、room.subscribe/subscribed/update/fatal/superseded/
    unsubscribe、message.send/ack）；
  - 错误码集合 13 个完全一致（turing_account_required、turing_client_outdated、
    turing_compliance_v*、turing_external_link_blocked、turing_match_verification_*、
    turing_phone_verification_required、turing_private_info_blocked、turing_queue_full、
    turing_room_gone、turing_security_calibration_*、turing_socket_unavailable）；
  - message.send body `{roomId, sessionId, clientMessageId, text}`（responseType
    message.ack）不变；guess body `{sessionId, guess}` 不变；
  - leave body `{ticketId, roomId, sessionId}`（带房间）或 `{ticketId, sessionId}`
    （仅排队）不变，与客户端实现一致。
- **变化 ①：start 请求体移除 `nickname` 字段**（新版前端不再发送，服务端从
  JWT token 取昵称）。旧客户端仍发 nickname 属多余字段，预计被服务端宽容忽略；
  协议客户端保留发送以支持自定义显示名，观察是否被拒（若 start 开始报错再移除）。
- **变化 ②：匹配安全挑战机制（新端点 + 新字段）**：
  - config 新增 `matchProofOfWorkRequired`（bool）。为 true 时（前端 UI 显示
    「实名认证已开启」「每次开始匹配前都会在本地自动完成一次安全验证码验算」），
    start 前先 `GET /api/turing/match-security-challenge`；
  - 响应 `{required: false}` → 无需挑战，跳过；否则为 altcha 挑战对象，
    本地完成 PoW 验算后得到 `altcha` 字符串；
  - start body 条件性新增 `matchAltcha: <altcha 字符串>`（展开进 body，
    与 guest-security-challenge 结果并列）；
  - 访客路径不变：`GET /api/turing/guest-security-challenge` → 响应对象直接
    展开进 start body（securityCalibrationToken 字段名已不在前端源码出现，
    服务端响应透传，字段名由服务端决定——注意旧版字段名可能已改）。
  - **客户端影响**：Python 客户端暂无 altcha PoW 实现；若服务端实际开启
    matchProofOfWorkRequired，start 可能被拒（预期错误码 turing_match_
    verification_required/failed 或 400）。观察项：开启后需实现 altcha
    PoW 求解（hashcash 风格：对 challenge+salt+number 做 SHA-256 前缀碰撞，
    Python hashlib 可实现）并打 match-security-challenge 拿 matchAltcha。
- **变化 ③：verificationMode 新增取值 `"arithmetic"`**（算术验证码），与
  "altcha" 并列；`registrationDefaultMode` 新增 "phone"（手机号注册优先）。
  影响注册/验证 UI 流程，不影响对局协议；config 解析前端按
  `=== "arithmetic" ? "arithmetic" : "altcha"` 归一化。
- **变化 ④：config 新增字段**（start 响应与 /auth/account-access 共享结构，
  客户端宽容解析不受影响）：
  `matchProofOfWorkRequired / phoneVerifiedMatchRequired / emergencySecurityNotice /
  phoneAuthEnabled / registrationDefaultMode / phoneVerification{required,ready,...} /
  preRoomAnnouncement / guestForcedAiEnabled / guestForcedAiPercent /
  smsDailyBudget / smsDailyUsage{used,distinctPhones,distinctClients,windowHours} /
  registrationRequired`。
  其中 `phoneVerifiedMatchRequired`（手机验证匹配门槛）与 `preRoomAnnouncement`
  （入房前公告）为对局前门槛/提示，错误码 turing_phone_verification_required
  已覆盖前者行为；`guestForcedAi*`（游客强制 AI 匹配开关/百分比）影响匹配
  体验不涉及协议。
- **变化 ⑤：房间状态 HTTP 回退轮询**（容错机制，非主协议）：
  `GET /api/turing/rooms/{roomId}?sessionId=...&after=<seq>&afterSequence=<seq>`
  返回房间快照（同 room.update 解析）。用途：WS 断线/不支持时的增量续订兜底；
  成功间隔基础轮询、失败指数退避（上限 + 随机抖动），页面隐藏时用更长间隔。
  协议客户端已有 WS 断线重连 + 增量续订（after/afterSequence），无需 HTTP 轮询。
- **变化 ⑥：前端框架 React 19.2.0**（升级，无协议影响）；注册表单新增实名
  字段 `realName / idNumber`（国内实名认证要求，注册/验证流程，不影响对局）；
  设置面板本地项 `enterToSend / sound / reducedMotion / verdictStampEnabled`
  （localStorage 本地偏好，不上送协议）。
- **维护模式/版本一致性前置检查**（旧版已有，补记）：start 前检查
  `/maintenance` 状态（维护中直接拦截，文案「网站维护中，请稍后访问。」）；
  clientVersion 与 serviceVersion 不一致时前端拦截（「页面与服务版本不一致，
  请刷新页面；若仍出现，请重启后端服务。」）——印证 clientVersion 必须保持
  与最新前端同步，否则 start 被拒（turing_client_outdated）。
- 适配动作：仅更新 `client_version` 默认值（src/turing_game/models.py）。
  matchProofOfWorkRequired / nickname 移除属观察项（服务端开启与否未实测），
  未改 start 请求构造；若 start 开始返回 match_verification_* 或 400，
  再实现 matchAltcha 流程并移除 nickname。



### 2026-08-09 12:00：前端资产更新（watch 触发适配 #2）

- 前端资产变化：`index-CX6W-B3M.js` + `index-D5iVH8o3.css`
  → `index-Cb0bc0Sy.js` + `index-D5iVH8o3.css`（CSS 未变；JS 仍 640,768 bytes，
  md5 2bff0876 → 4c4bcda1）。首页 HTML 引用带 `?v=a34a6e1d5c98`（= 新 clientVersion 前缀）。
- **clientVersion 更新**：`fd41c0cd17233dc464c8df990400a43d90bc08ed`
  → `a34a6e1d5c98915b78f510583a32dfa688e49f1a`。
  客户端 `models.py` 默认值已同步（可被 TT_CLIENT_VERSION 覆盖）。
- **diff 仅 3 处**（新旧全量逐行对比）：
  1. 第 1/17 行：admin 面板 chunk 重建（TuringAdminPanel-3Tx-rKs0 →
     BimBAdxe、zap-OA22W76V → T1NCf0P-、WeirdChatAdminPanel-sw4QodXB →
     C4xzc56K）——admin 专属，不影响协议客户端；
  2. 第 21 行：`mm` 常量（clientVersion）更新，如上。
  其余常量（zp=3 协议版本、8e3/2e4/5e3/15e3/3e4/90e3/1800e3 时间参数）零变化。
- **协议面零变化**（新旧全量特征对比确认）：
  - WS 消息类型 13 种完全一致（match.subscribe/subscribed/update/fatal/
    unsubscribe、room.subscribe/subscribed/update/fatal/superseded/unsubscribe、
    message.send/ack）；
  - 错误码集合 13 个完全一致（与 2026-08-07 记录相同）；
  - 端点不变：`/api/turing/socket`、`/api/auth/account-access`、
    match-security-challenge、guest-security-challenge、extend-chat；
  - 字段不变：matchAltcha / matchProofOfWorkRequired / funMatchEnabled /
    clientMessageId / afterSequence / preRoomAnnouncement 等全部存在。
- 适配动作：仅更新 `client_version` 默认值（src/turing_game/models.py），
  无协议机制变化 → 未改 WS/状态机代码。观察项（matchProofOfWorkRequired
  是否已开启、nickname 是否被拒）延续 2026-08-07 记录，继续观察。

### 2026-08-10 12:00：前端资产更新（watch 触发适配 #3）

- 前端资产变化：`index-Cb0bc0Sy.js` + `index-D5iVH8o3.css`
  → `index-uckJV3wA.js` + `index-DbCjXzRz.css`（Vite 重新构建，
  JS 640,768 → 641,444 bytes；CSS 更新，旧 CSS 文件名已不在首页引用）。
  首页 HTML 引用带 `?v=2a5cca135352`（= 新 clientVersion 前缀）。
- **clientVersion 更新**：`a34a6e1d5c98915b78f510583a32dfa688e49f1a`
  → `2a5cca135352f10e7e026eb9d6d58215e0ced3e8`。
  客户端 `models.py` 默认值已同步；Hermes config.yaml
  `TT_CLIENT_VERSION` 同步更新（hermes config set 写入；
  注意该 env 此前停在 8cb7adea（08-05 值），08-06/08-07/08-09
  三轮只改了仓库 models.py 未同步 config——env 覆盖优先级高于
  models.py，需重启 Hermes 使 MCP server 重新注入 env）。
- **协议面零变化**（新旧全量特征对比确认）：
  - WS 消息类型 13 种完全一致（match.subscribe/subscribed/update/fatal/
    unsubscribe、room.subscribe/subscribed/update/fatal/superseded/
    unsubscribe、message.send/ack）；
  - 错误码集合 12 个完全一致（turing_account_required、
    turing_client_outdated、turing_compliance_v*、
    turing_external_link_blocked、turing_match_verification_*、
    turing_phone_verification_required、turing_private_info_blocked、
    turing_queue_full、turing_room_gone、
    turing_security_calibration_*、turing_socket_unavailable）；
  - 硬编码端点仅 `/api/auth/account-access` + `/api/turing/socket`，
    其余模板拼接，与旧版一致；match-security-challenge /
    guest-security-challenge / extend-chat / rooms/{id}/guess 不变；
  - start body 字段全一致（nickname 仍不在前端发送，延续 08-07 观察；
    protocolVersion=3 / clientVersion / chatDurationSec / matchTimeoutSec /
    funMatchEnabled / allowAnonymousChatResearch /
    registeredPrivacyNoticeVersion / matchAltcha / debugParams）；
  - chatExtension/告别期字段集、afterSequence 增量续订、
    securityRequirement、matchProofOfWorkRequired、preRoomAnnouncement
    全部存在，与旧版一致。
- **变化 ①：维护模式 UI 升级为微信小游戏推广页**（仅前端 UI，未启用）：
  旧版维护弹窗（`turing-maintenance-icon` + 文案「网站维护中，请稍后
  访问。」）被替换为多平台引导页：CSS 类 `turing-maintenance-platforms` /
  `turing-maintenance-wechat` / `turing-maintenance-wechat-copy`，
  新增静态资源 `/assets/turing-wechat-minigame-qr-Fftpuclj.jpg`
  （微信小游戏二维码），文案「全民图灵测试微信小游戏码」「支持
  微信/QQ 双平台」「正在内测中」「网页版仍在维护中，请等待通知」
  「网页版本暂不可用，欢迎使用微信小游戏版本：」。`/maintenance`
  轮询逻辑保留（15s + visibilitychange）。2026-08-10 实测
  `/maintenance` 返回 200 空响应（非 JSON）→ 维护模式未启用，
  网页版当前可正常访问。
- **变化 ②：服务端运行时配置变化**（非前端代码，实测 account-access）：
  `registrationRequired: true`、`guestMatchLimit: 0`（此前记录为 1）——
  游客匹配已关闭，未注册账号 start 预期被拒（turing_account_required）；
  `matchProofOfWorkRequired: false`（PoW 仍未开启，观察项延续）、
  `phoneVerifiedMatchRequired: false`、`registrationDefaultMode:
  "password"`、`phoneVerification{required:true,ready:true,
  provider:"aliyun-pnvs",codeLength:6,validSeconds:300,
  resendSeconds:60}`（手机验证就绪，账号侧要求，不影响已注册账号
  的对局协议）。
- admin 面板 chunk 重建（TuringAdminPanel-5phlshn9 / zap-DDf3xLGx /
  WeirdChatAdminPanel-BdkczFof），admin 专属，不影响协议客户端。
- 适配动作：仅更新 `client_version` 默认值（src/turing_game/models.py）
  + config.yaml env 同步。无协议机制变化 → 未改 WS/状态机代码。
  观察项：matchProofOfWorkRequired 是否开启、维护模式是否启用
  （若启用，start 会被服务端拒绝，以错误码为准）、游客注册门槛
  变化是否影响 MCP 客户端（已注册账号不受影响）。

### 2026-08-11 12:00：前端资产更新（watch 触发适配 #4）

- 前端资产变化：`index-uckJV3wA.js` + `index-DbCjXzRz.css`
  → `index-B-A_bZfd.js` + `index-DbCjXzRz.css`（CSS 未变；JS 仍
  641,444 bytes）。首页 HTML 引用带 `?v=ab69c7ccdd2b`
  （= 新 clientVersion 前缀）。
- **clientVersion 更新**：`2a5cca135352f10e7e026eb9d6d58215e0ced3e8`
  → `ab69c7ccdd2b25c9c3f5ff58f403e8fe4939ec45`。
  客户端 `models.py` 默认值已同步；Hermes config.yaml
  `TT_CLIENT_VERSION` 已用 hermes config set 同步
  （注意：需重启 Hermes 使 MCP server 重新注入 env）。
- **全量 diff 仅 3 处单行变化，协议面零变化**：
  ① `__vite__mapDeps` admin chunk 名重建（TuringAdminPanel-5phlshn9
  → Cs0zian3、zap-DDf3xLGx → BqzeoCpQ、WeirdChatAdminPanel-BdkczFof
  → Bolmq8Nn），admin 专属，不影响协议客户端；
  ② Odd World Studio（怪奇世界创作工坊 game-studio 模块）前端更新
  （非图灵测试模块，与对局协议无关）；
  ③ clientVersion 常量 mm= 赋值更新。
  协议特征关键词对比（WS 消息类型 13 种、错误码 12 个、硬编码端点
  /api/auth/account-access + /api/turing/socket、start body 字段、
  chatExtension/告别期字段、afterSequence、securityRequirement、
  matchProofOfWorkRequired、preRoomAnnouncement、debugParams AI 参数
  Fg、localStorage key anyanygame.turing.*）新旧完全一致。
- 适配动作：仅更新 `client_version` 默认值（src/turing_game/models.py）
  + config.yaml env 同步。无协议机制变化 → 未改 WS/状态机代码。
  观察项延续 2026-08-10：matchProofOfWorkRequired 是否开启、维护
  模式（微信小游戏推广页）是否启用、游客注册门槛变化。


### 2026-08-12 12:00：前端资产更新（watch 触发适配 #5）

- 前端资产变化：`index-B-A_bZfd.js` + `index-DbCjXzRz.css`
  → `index-DWHZD6Gp.js` + `index-Dw1I_hmR.css`（JS 仍 641,444 bytes，
  CSS 148,078 → 148,141 bytes）。
- **clientVersion 更新**：`ab69c7ccdd2b25c9c3f5ff58f403e8fe4939ec45`
  → `588dc7a68ce43dd0fd1d2cb6da5a3846d72b4b8f`。
  客户端 `models.py` 默认值已同步；Hermes config.yaml
  `TT_CLIENT_VERSION` 已同步（注意：需重启 Hermes 使 MCP server
  重新注入 env）。
- **全量 diff 极小（JS 75 字节差异，仅 2 处），协议面零变化**：
  ① `__vite__mapDeps` admin chunk 名重建（TuringAdminPanel-Cs0zian3
  → CfAVMNlo、zap-BqzeoCpQ → AB7udjZe、WeirdChatAdminPanel-Bolmq8Nn
  → 2rSIug1C），admin 专属，不影响协议客户端；
  ② clientVersion 常量赋值更新（mm=）。
  CSS 差异仅新增 Tailwind 工具类（如 `.sm\:grid-cols-5`），纯 UI 层。
  协议特征关键词对比（WS 消息类型、错误码集合、端点
  /api/auth/account-access + /api/turing/socket、start body 字段、
  chatExtension/告别期字段、afterSequence、securityRequirement、
  matchProofOfWorkRequired、preRoomAnnouncement）新旧完全一致。
- 适配动作：仅更新 `client_version` 默认值（src/turing_game/models.py）
  + config.yaml env 同步。无协议机制变化 → 未改 WS/状态机代码。
  观察项延续 2026-08-10/08-11：matchProofOfWorkRequired 是否开启、
  维护模式（微信小游戏推广页）是否启用、游客注册门槛变化。

### 2026-08-13 12:01：前端资产更新（watch 触发适配 #6）

- 前端资产变化：`index-DWHZD6Gp.js` + `index-Dw1I_hmR.css`
  → `index-C9NdivmR.js` + `index-D4l9Q9qb.css`（JS 641,444 → 640,789
  bytes，CSS 148,141 → 148,021 bytes）。
- **clientVersion 更新**：`588dc7a68ce43dd0fd1d2cb6da5a3846d72b4b8f`
  → `c6e81308a242534c363aed9464e1fca7e762aabf`（首页 HTML
  `?v=c6e81308a242` 交叉验证一致）。客户端 `models.py` 默认值已同步；
  Hermes config.yaml `TT_CLIENT_VERSION` 已同步（需重启 Hermes 使
  MCP server 重新注入 env）。
- **协议面零变化**（已逐项核对）：
  - WS 消息类型 21 种全一致（协议相关：match.subscribe/unsubscribe、
    message.send、room.subscribe/unsubscribe；responseType 3 种
    message.ack/room.subscribed 等全一致）；
  - 端点 `/api/auth/account-access` + `/api/turing/socket` 不变；
  - 发送双通道机制不变：WS `message.send`（8s 超时）→ 失败
    （`turing_socket_unavailable`）→ HTTP POST
    `/api/turing/rooms/{id}/messages` fallback；`message_cooldown`
    且 retryAfterMs≤1000 时等 retryAfterMs+30ms 重试一次；错误码
    content_blocked/turing_external_link_blocked/
    turing_private_info_blocked 仍在（旧 JS 已有同款，本次仅
    minifier 变量重命名 NS→jS、zm→Rm 等）；
  - 本次 JS 大 diff（1.27MB）主因是 React 19.2 库代码的 minifier
    变量名重排（Dd→Rd、ce→ie 等），非业务逻辑变化。
- **前端 UI 状态机简化（纯 UI，不影响协议）**：消息 deliveryStatus
  状态从 `pending`/`retrying`/`sent`/`failed` 收敛为仅 `sent`
  （`pending_` 乐观 ID、「待确认」小字、`turing-message-retry`
  「发送失败 · 点击重试」内联按钮均删除；失败改为自动重试一次 +
  抛「消息发送失败，请重试」）。deliveryStatus 非协议字段，MCP
  客户端不依赖。
- 适配动作：仅更新 `client_version` 默认值（src/turing_game/models.py）
  + config.yaml env 同步。无协议机制变化 → 未改 WS/状态机代码。
  观察项延续 2026-08-10~12：matchProofOfWorkRequired 是否开启、
  维护模式（微信小游戏推广页）是否启用、游客注册门槛变化。

### 2026-08-14 12:01：前端资产更新（watch 触发适配 #7）

- 前端资产变化：`index-C9NdivmR.js` → `index-D3tP2GCZ.js`（JS
  640,789 → 640,789 bytes，等长替换；无 CSS 变化）。
- **clientVersion 更新**：`c6e81308a242534c363aed9464e1fca7e762aabf`
  → `a9f7062a68ef4c060fc039930fbc0e791f1ed0a7`（首页 HTML
  `?v=a9f7062a68ef` 交叉验证一致）。客户端 `models.py` 默认值已同步；
  Hermes config.yaml `TT_CLIENT_VERSION` 已同步（需重启 Hermes 使
  MCP server 重新注入 env）。
- **协议面零变化**（diff 仅 2 处、等长替换）：
  ① `__vite__mapDeps` admin chunk 名重建（TuringAdminPanel-D_kqECt8
  → CzhnwMBT、zap-DZrW6LQT → D3mpf8mX、WeirdChatAdminPanel-Cigk-9JR
  → BZEw65a3），admin 专属，不影响协议客户端；
  ② clientVersion 常量赋值更新（dm=）。
  协议特征关键词集合（WS 消息类型 7 种、端点、错误码 6 种、
  afterSequence/securityRequirement/matchProofOfWorkRequired/
  preRoomAnnouncement/chatExtension/guestMatchLimit）新旧完全一致。
- 适配动作：仅更新 `client_version` 默认值（src/turing_game/models.py）
  + config.yaml env 同步。无协议机制变化 → 未改 WS/状态机代码。
  观察项延续 2026-08-10~13：matchProofOfWorkRequired 是否开启、
  维护模式（微信小游戏推广页）是否启用、游客注册门槛变化。

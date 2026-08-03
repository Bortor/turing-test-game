"""告别期（chatExtension）状态机快速验证 — 2026-08-02"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from turing_game.client import TuringClient
from turing_game.models import GameState

client = TuringClient()
client._room_id = "room-1"
client._session_id = "sess-1"

passed = []


def check(name, cond, detail=""):
    status = "PASS" if cond else "FAIL"
    passed.append(cond)
    print(f"[{status}] {name} {detail}")


# --- 1. ended 房间 + chatExtension 解析 ---
client.state = GameState.ACTIVE
client._apply_room({
    "roomId": "room-1",
    "state": "ended",
    "chatExtension": {"available": True, "canSend": False, "reviewOnly": False,
                      "selfReturned": False},
})
check("ended 映射为 RESULT", client.state == GameState.RESULT, f"state={client.state}")
check("chatExtension 已解析", client._chat_extension is not None and client._chat_extension["available"] is True,
      f"ext={client._chat_extension}")

# --- 2. RESULT + 有 chatExtension → wait_event 不立即 finished ---
snap = client.snapshot()
async def _wait_check():
    # 没有事件时，RESULT+chatExtension 应继续等待直到超时（不是 finished）
    r = await client.wait_event(0.3)
    return r
r = asyncio.run(_wait_check())
check("RESULT+chatExtension 不立即 finished", r.get("finished") is not True, f"finished={r.get('finished')}")

# --- 3. extended 房间 → EXTENDED 状态，不被 _my_guess 覆盖 ---
client._my_guess = "human"
client.state = GameState.RESULT
client._apply_room({
    "roomId": "room-1",
    "state": "extended",
    "chatExtension": {"available": True, "canSend": True, "active": True,
                      "selfReturned": True, "opponentDeparted": False},
})
check("extended 映射为 EXTENDED", client.state == GameState.EXTENDED, f"state={client.state}")
check("EXTENDED 不被 _my_guess 覆盖为 LOCKED_WAIT", client.state == GameState.EXTENDED)

# --- 4. snapshot.can_send 在 EXTENDED+canSend 为 True ---
check("EXTENDED+canSend → can_send=True", client.snapshot()["can_send"] is True)
check("chat_extension 暴露在 snapshot", client.snapshot()["chat_extension"] == client._chat_extension)

# --- 5. send_message 状态限制 ---
async def try_send():
    try:
        return await client.send_message("告别测试")
    except Exception as e:
        return str(e)
r = asyncio.run(try_send())
# 没有 WS 会抛「WebSocket 尚未连接」，但不应报状态类错误
check("EXTENDED+canSend 允许 send_message（不报状态错误）",
      "不在可聊天状态" not in str(r) and "告别期不可发送" not in str(r),
      f"resp={str(r)[:120]}")

# --- 6. EXTENDED + 只读（canSend=False）→ 拒绝 ---
client._chat_extension = {"canSend": False}
async def try_send2():
    try:
        await client.send_message("只读测试")
        return "no-error"
    except Exception as e:
        return str(e)
err = asyncio.run(try_send2())
check("EXTENDED+只读 → send_message 拒绝", "告别期不可发送" in err, f"err={err}")

# --- 8. submit_guess 响应带 chatExtension（结算响应即告别期开始） ---
import json
from unittest.mock import patch as mock_patch

client2 = TuringClient()
client2._room_id = "room-2"
client2._session_id = "sess-2"
client2._guess_unlocks_at_ms = None  # 判定已解锁

async def fake_guess(path, method="POST", body=None, auth=False):
    return {
        "roomId": "room-2",
        "state": "ended",
        "guessState": {"firstLockedBy": "self", "opponentLocked": True},
        "chatExtension": {"available": True, "canSend": False,
                          "reviewOnly": False, "selfReturned": False},
        "result": {"correct": True, "actualType": "human", "reason": "both-locked"},
    }

with mock_patch.object(client2, "_http_json", side_effect=fake_guess):
    r = asyncio.run(client2.submit_guess("human"))
check("submit_guess 解析响应 chatExtension", client2._chat_extension is not None and client2._chat_extension["available"] is True,
      f"ext={client2._chat_extension}")
check("submit_guess 后 RESULT + 有 chatExtension → wait_event 不 finished",
      asyncio.run(client2.wait_event(0.2)).get("finished") is not True)

# --- 9. RESULT 无 chatExtension → 立即 finished（旧行为保留） ---
client._chat_extension = None
client.state = GameState.RESULT
r = asyncio.run(client.wait_event(0.3))
check("RESULT 无 chatExtension → 立即 finished", r.get("finished") is True)

print("PASS:", sum(passed), "/", len(passed))
if not all(passed):
    sys.exit(1)

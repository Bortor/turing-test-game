#!/usr/bin/env python3
"""Pure-API Turing test client - full flow validation.
Login -> start (queue) -> WS match.subscribe -> wait match.update -> room.subscribe -> message.send -> guess.
"""
import json
import os
import ssl
import threading
import time
import uuid
import urllib.request
import urllib.error
import websocket  # pip install websocket-client

BASE = "https://www.anyanygame.com"
WSS = "wss://www.anyanygame.com/api/turing/socket"
USER = os.environ["TT_USERNAME"]
PW = os.environ["TT_PW"]
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"

VID = str(uuid.uuid4())

def req(path, method="GET", body=None, headers=None, timeout=20):
    url = BASE + path
    data = json.dumps(body, ensure_ascii=False).encode() if body is not None else None
    h = {"User-Agent": UA, "Content-Type": "application/json", "Origin": BASE, "Referer": BASE + "/turing-test"}
    if headers:
        h.update(headers)
    r = urllib.request.Request(url, data=data, headers=h, method=method)
    try:
        with urllib.request.urlopen(r, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode())
        except Exception:
            return e.code, {}

# ① login
st, d = req("/api/auth/turing-login", "POST", {"identifier": USER, "password": PW})
print("① login:", st, "token:", (d.get("token") or "")[:30], "...")
token = d["token"]

# ② start
st, d = req("/api/turing/start", "POST", {
    "nickname": os.environ.get("TT_NICKNAME", USER), "protocolVersion": 3,
    # 运行前需替换为当前抓包到的 clientVersion（服务端会校验该字段）
    "clientVersion": "0000000000000000000000000000000000000000",
    "chatDurationSec": 600, "matchTimeoutSec": 30,
    "allowAnonymousChatResearch": False, "registeredPrivacyNoticeVersion": 1,
}, {"Authorization": f"Bearer {token}", "X-Visitor-Id": VID})
print("② start:", st, "status:", d.get("ticket", {}).get("status"), "queuePos:", d.get("ticket", {}).get("queuePosition"))
ticket = d["ticket"]
ticket_id = ticket["ticketId"]
session_id = ticket["sessionId"]

# ③ WS connect + match.subscribe
events = []
ws = None

def on_message(ws_, msg):
    print("WS ←", msg[:400])
    events.append(json.loads(msg))

def on_error(ws_, err):
    print("WS ERR:", err)

def on_close(ws_, code, reason):
    print("WS CLOSE:", code, reason)

ws = websocket.WebSocketApp(WSS, on_message=on_message, on_error=on_error, on_close=on_close,
                            header={"Authorization": f"Bearer {token}", "X-Visitor-Id": VID})
wst = threading.Thread(target=ws.run_forever, daemon=True)
wst.start()
time.sleep(1.5)

print("③ WS subscribe...")
ws.send(json.dumps({"type": "match.subscribe", "requestId": str(uuid.uuid4()),
                    "ticketId": ticket_id, "sessionId": session_id}))

# ④ wait for match.update (queue progress), timeout 150s
deadline = time.time() + 150
matched = False
while time.time() < deadline:
    time.sleep(2)
    for ev in events:
        if ev.get("type") == "match.update":
            status = ev.get("status")
            print("④ match.update:", json.dumps(ev, ensure_ascii=False)[:500])
            if isinstance(status, dict) and status.get("status") in ("matched", "calibrating", "active"):
                matched = True
                break
    if matched:
        break

ws.close()
print("done, events:", len(events))

#!/usr/bin/env python3
"""Full pure-API flow: login -> start match -> inspect response."""
import json
import os
import urllib.request
import urllib.error

BASE = "https://www.anyanygame.com"
USER = os.environ["TT_USERNAME"]
PW = os.environ["TT_PW"]

def req(path, method="GET", body=None, headers=None):
    url = BASE + path
    data = json.dumps(body, ensure_ascii=False).encode() if body is not None else None
    h = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
        "Content-Type": "application/json",
        "Origin": BASE,
        "Referer": BASE + "/turing-test",
    }
    if headers:
        h.update(headers)
    r = urllib.request.Request(url, data=data, headers=h, method=method)
    try:
        with urllib.request.urlopen(r, timeout=15) as resp:
            return resp.status, resp.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()

# 1. login
st, out = req("/api/auth/turing-login", "POST", {"identifier": USER, "password": PW})
print("login:", st)
login = json.loads(out)
token = login.get("token")
print("token len:", len(token) if token else None)

# 2. start match with token + visitor id
vid = os.environ.get("TT_VID", str(__import__("uuid").uuid4()))
st, out = req("/api/turing/start", "POST", {
    "nickname": os.environ.get("TT_NICKNAME", USER),
    "protocolVersion": 3,
    # 运行前需替换为当前抓包到的 clientVersion（服务端会校验该字段）
    "clientVersion": "0000000000000000000000000000000000000000",
    "chatDurationSec": 600,
    "matchTimeoutSec": 30,
    "allowAnonymousChatResearch": False,
    "registeredPrivacyNoticeVersion": 1,
}, {"Authorization": f"Bearer {token}", "X-Visitor-Id": vid})
print("start:", st)
print(out[:1500])

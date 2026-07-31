#!/usr/bin/env python3
"""Test guess endpoint response structure (on an expired room to also capture error format)."""
import json
import os
import uuid
import urllib.request
import urllib.error

BASE = "https://www.anyanygame.com"
USER = os.environ["TT_USERNAME"]
PW = os.environ["TT_PW"]
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
VID = str(uuid.uuid4())

def req(path, method="GET", body=None, headers=None):
    url = BASE + path
    data = json.dumps(body, ensure_ascii=False).encode() if body is not None else None
    h = {"User-Agent": UA, "Content-Type": "application/json", "Origin": BASE, "Referer": BASE + "/turing-test"}
    if headers:
        h.update(headers)
    r = urllib.request.Request(url, data=data, headers=h, method=method)
    try:
        with urllib.request.urlopen(r, timeout=15) as resp:
            return resp.status, resp.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()

st, d = req("/api/auth/turing-login", "POST", {"identifier": USER, "password": PW})
token = json.loads(d)["token"]
print("login ok")

# guess on the earlier matched room (likely expired - captures error format)
st, out = req("/api/turing/rooms/room_example_expired/guess", "POST",
              {"sessionId": "session_example", "guess": "human"},
              {"Authorization": f"Bearer {token}", "X-Visitor-Id": VID})
print("guess(expired room):", st, out[:500])

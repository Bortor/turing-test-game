#!/usr/bin/env python3
"""Test pure-API login against anyanygame turing-test."""
import json
import os
import uuid
import urllib.request

BASE = "https://www.anyanygame.com"
USER = os.environ["TT_USERNAME"]
PW = os.environ["TT_PW"]

def req(path, method="GET", body=None, headers=None):
    url = BASE + path
    data = json.dumps(body).encode() if body is not None else None
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

# fresh visitor id
vid = str(uuid.uuid4())
print("visitor:", vid)

# 1. login with fresh visitor
st, out = req("/api/auth/turing-login", "POST", {"identifier": USER, "password": PW}, {"X-Visitor-Id": vid})
print("login(fresh):", st, out[:200])

# 2. login with no visitor header at all
st, out = req("/api/auth/turing-login", "POST", {"identifier": USER, "password": PW})
print("login(no-visitor):", st, out[:200])

# 3. check challenge endpoint (fresh visitor)
st, out = req("/api/turing/guest-security-challenge?verificationClient=dual", headers={"X-Visitor-Id": vid})
print("challenge(fresh):", st, out[:200])

# 4. account-access (fresh)
st, out = req("/api/auth/account-access", headers={"X-Visitor-Id": vid})
print("account-access(fresh):", st, out[:200])

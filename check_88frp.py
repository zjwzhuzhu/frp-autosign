# -*- coding: utf-8 -*-
"""88frp.com 每日自动签到

流程（逆向自站内 SPA）：
  1. POST https://api.88frp.com/api/auth/login  {"username","password"} → data.token
  2. POST https://api.88frp.com/api/domain/value-added-rights/signIn
     Header: Authorization: Bearer <token>
"""

import os
import sys
import json

import requests

API = "https://api.88frp.com"
USERNAME = os.getenv("FRP88_USERNAME", "")
PASSWORD = os.getenv("FRP88_PASSWORD", "")

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36"
)


def main() -> int:
    if not USERNAME or not PASSWORD:
        print("⏭  未配置 FRP88_USERNAME / FRP88_PASSWORD，跳过 88frp 签到")
        return 0

    s = requests.Session()
    s.headers.update(
        {
            "User-Agent": UA,
            "Origin": "https://88frp.com",
            "Referer": "https://88frp.com/",
            "Accept": "application/json, text/plain, */*",
        }
    )

    # 1. 登录
    try:
        r = s.post(
            f"{API}/api/auth/login",
            json={"username": USERNAME, "password": PASSWORD},
            timeout=30,
        )
        data = r.json()
    except Exception as e:
        print(f"✗ 88frp 登录请求失败: {e}")
        return 1

    if not data.get("success"):
        print(f"✗ 88frp 登录失败: {data.get('message') or data}")
        return 1

    token = (data.get("data") or {}).get("token")
    if not token:
        print(f"✗ 88frp 登录返回缺少 token: {json.dumps(data, ensure_ascii=False)[:200]}")
        return 1

    auth = {"Authorization": f"Bearer {token}"}
    print("✓ 88frp 登录成功")

    # 2. 查询用户信息（确认 token 可用）
    try:
        info = s.get(f"{API}/api/users/mine", headers=auth, timeout=30).json()
        uname = (info.get("data") or {}).get("username", "?")
        print(f"✓ 88frp 用户: {uname}")
    except Exception as e:
        print(f"⚠ 88frp 查询用户信息失败（继续签到）: {e}")

    # 3. 签到
    try:
        r = s.post(
            f"{API}/api/domain/value-added-rights/signIn", headers=auth, timeout=30
        )
        res = r.json()
    except Exception as e:
        print(f"✗ 88frp 签到请求失败: {e}")
        return 1

    msg = res.get("message") or ""
    if res.get("success"):
        print(f"✓ 88frp 签到成功: {msg or 'ok'}")
        return 0
    if "已签到" in msg:
        print(f"✓ 88frp 今日已签到: {msg}")
        return 0

    print(f"✗ 88frp 签到失败: HTTP {r.status_code} {json.dumps(res, ensure_ascii=False)[:300]}")
    return 1


if __name__ == "__main__":
    sys.exit(main())

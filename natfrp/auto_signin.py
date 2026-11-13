"""
SakuraFRP (natfrp.com) 自动签到 - 纯 HTTP 协议版

流程: HTTP 登录(OpenID) → GeeTest 验证码协议破解 → AI 视觉识别 → POST 签到

来源: 基于 MIT 协议项目 claaudy/sakurafrp-auto-sign 移植（见 NOTICE.md）。
本文件仅做环境变量与 CI 退出码适配。
"""

import ast
import json
import os
import sys
import time
from pathlib import Path

import httpx
import requests
from dotenv import load_dotenv
from openai import OpenAI

from urllib.parse import urljoin

from geetest_crack import GeeTestCrack
from nine_grid_solver import solve_nine_grid as solve_nine_grid_local

# ── 加载环境变量 ──────────────────────────────────────────────
load_dotenv(Path(__file__).parent / ".env")
USERNAME = os.getenv("NATFRP_USERNAME") or os.getenv("username", "")
PASSWORD = os.getenv("NATFRP_PASSWORD") or os.getenv("password", "")

CAPTCHA_API_BASE = (
    os.getenv("VISION_API_BASE")
    or os.getenv("CAPTCHA_API_BASE")
    or "https://api.openai.com/v1"
)
CAPTCHA_API_KEY = os.getenv("VISION_API_KEY") or os.getenv("CAPTCHA_API_KEY", "")
CAPTCHA_MODEL = os.getenv("VISION_MODEL") or os.getenv("CAPTCHA_MODEL", "gpt-4o")

MAX_RETRIES = int(os.getenv("MAX_RETRIES", "10"))

MOUSE_PATH_FILE = str(Path(__file__).parent / "mousepath.json")

# ── 通用请求头 ────────────────────────────────────────────────
COMMON_HEADERS = {
    "accept": "application/json, text/plain, */*",
    "accept-language": "zh-CN,zh;q=0.9,en;q=0.8",
    "cache-control": "no-cache",
    "pragma": "no-cache",
    "sec-ch-ua": '"Chromium";v="145", "Not:A_Brand";v="99"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"macOS"',
    "sec-fetch-dest": "empty",
    "sec-fetch-mode": "cors",
    "sec-fetch-site": "same-origin",
    "user-agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36"
    ),
}

OPENID_AJAX_HEADERS = {
    "accept": "application/json, text/javascript, */*; q=0.01",
    "x-requested-with": "XMLHttpRequest",
}
def _create_client(follow_redirects: bool = False) -> httpx.Client:
    return httpx.Client(
        follow_redirects=follow_redirects,
        timeout=30.0,
        headers=COMMON_HEADERS,
    )


def _prime_openid_session(client: httpx.Client) -> None:
    """建立 OAuth 会话上下文: natfrp → oauth/authorize → openid login"""
    resp = client.get("https://www.natfrp.com/cgi/user/login")
    # 手动跟完整条重定向链，确保 /oauth/authorize 被访问到
    step = 0
    while resp.is_redirect and step < 10:
        location = resp.headers.get("location")
        if not location:
            break
        next_url = urljoin(str(resp.url), location)
        referer = str(resp.url)
        resp = client.get(next_url, headers={"referer": referer})
        step += 1
        print(f"  prime[{step}]: {resp.status_code} -> {resp.url}")
    # 最终应该落在 openid.13a.com/login


def _follow_openid_redirect(client: httpx.Client) -> None:
    """完成 OpenID -> natfrp 的登录态桥接"""
    resp = client.get(
        "https://openid.13a.com/redirect",
        headers={"referer": "https://openid.13a.com/login"},
    )
    print(f"  OpenID redirect: {resp.status_code} -> {resp.url}")

    redirect_steps = 0
    while resp.is_redirect and redirect_steps < 10:
        location = resp.headers.get("location")
        if not location:
            break
        next_url = urljoin(str(resp.url), location)
        referer = str(resp.url)
        resp = client.get(next_url, headers={"referer": referer})
        redirect_steps += 1
        print(f"  follow redirect[{redirect_steps}]: {resp.status_code} -> {resp.url}")


def _extract_message_content(response) -> str:
    """兼容不同 OpenAI 兼容实现，尽量提取文本内容"""
    choices = getattr(response, "choices", None) or []
    if choices:
        message = getattr(choices[0], "message", None)
        if message is not None:
            content = getattr(message, "content", None)
            if isinstance(content, str):
                return content.strip()
            if isinstance(content, list):
                parts = []
                for item in content:
                    if isinstance(item, dict) and item.get("type") == "text":
                        parts.append(item.get("text", ""))
                text = "\n".join(part for part in parts if part).strip()
                if text:
                    return text

    data = getattr(response, "model_dump", lambda: None)()
    if isinstance(data, dict):
        choices = data.get("choices") or []
        if choices:
            message = choices[0].get("message") or {}
            content = message.get("content")
            if isinstance(content, str):
                return content.strip()
            if isinstance(content, list):
                parts = [item.get("text", "") for item in content if isinstance(item, dict) and item.get("type") == "text"]
                text = "\n".join(part for part in parts if part).strip()
                if text:
                    return text
    return ""


def _strip_json_fence(text: str) -> str:
    text = text.strip()
    if text.startswith("```json") and text.endswith("```"):
        return text[7:-3].strip()
    if text.startswith("```") and text.endswith("```"):
        return text[3:-3].strip()
    return text


def _solve_click_captcha(crack) -> str:
    """登录阶段的图片验证码求解 (与签到共用 AI 识别逻辑)"""
    for attempt in range(1, MAX_RETRIES + 1):
        print(f"\n  --- 登录验证码尝试 {attempt}/{MAX_RETRIES} ---")
        pic_type, pic_url = crack.get_pic(0 if attempt == 1 else attempt)
        print(f"  验证码类型: {pic_type}")

        points = _recognize_captcha(pic_url, pic_type)
        if not points:
            print("  ✗ 识别失败，重试 ...")
            time.sleep(2)
            continue
        print(f"  识别结果: {points}")

        result = crack.verify(points)
        print(f"  验证结果: {result}")

        if result.get("status") == "success" and result.get("data", {}).get("result") == "success":
            validate = result["data"]["validate"]
            print("  ✓ 验证码通过!")
            return validate
        else:
            print("  ✗ 验证失败，重试 ...")
            time.sleep(2)

    raise RuntimeError(f"登录验证码重试 {MAX_RETRIES} 次均失败")



def login() -> httpx.Client:
    """
    纯 HTTP 登录流程:
    1. 获取 OpenID GeeTest 验证码配置
    2. 破解 GeeTest 获取 validate
    3. POST 登录
    4. 获取 session cookies
    """
    print("[1/3] 正在登录 ...")

    client = _create_client(follow_redirects=True)
    _prime_openid_session(client)

    # 1.1 获取 OpenID 的 GeeTest 配置
    print("  获取验证码配置 ...")
    resp = client.get(
        "https://openid.13a.com/cgi/captcha?login",
        headers={"referer": "https://openid.13a.com/login", **OPENID_AJAX_HEADERS},
    )
    captcha_data = resp.json()
    if not captcha_data.get("success"):
        raise RuntimeError(f"获取验证码配置失败: {captcha_data}")

    gt = captcha_data["message"]["gt"]
    challenge = captcha_data["message"]["challenge"]
    print(f"  GT: {gt[:16]}...  Challenge: {challenge[:16]}...")

    # 1.2 第一轮 GeeTest 交互，浏览器登录流在这里就拿到 validate
    print("  执行登录验证码握手 ...")
    crack = GeeTestCrack(gt, challenge, MOUSE_PATH_FILE, referer="https://openid.13a.com/")
    crack.get_type()
    crack.get_c_s()
    ajax_result = crack.ajax()

    validate = ajax_result.get("validate")
    print(f"  ajax 返回: {json.dumps(ajax_result, ensure_ascii=False)[:200]}...")
    if ajax_result.get("result") == "click":
        validate = _solve_click_captcha(crack)
    elif not validate:
        crack.close()
        raise RuntimeError(f"登录验证码未返回 validate: {ajax_result}")
    else:
        print(f"  验证成功! validate: {validate[:16]}...")

    # 1.3 POST 登录到 OpenID
    print("  提交登录 ...")
    login_data = {
        "username": USERNAME,
        "password": PASSWORD,
        "geetest_id": challenge,
        "geetest_challenge": challenge,
        "geetest_validate": validate,
        "geetest_seccode": f"{validate}|jordan",
    }
    resp = client.post(
        "https://openid.13a.com/cgi/password/login",
        data=login_data,
        headers={
            "referer": "https://openid.13a.com/login",
            "content-type": "application/x-www-form-urlencoded; charset=UTF-8",
            **OPENID_AJAX_HEADERS,
        },
    )

    if resp.status_code not in (200, 302):
        crack.close()
        raise RuntimeError(f"登录请求失败: {resp.status_code} {resp.text[:200]}")

    # 1.6 完成 OpenID -> natfrp 跳转桥接
    _follow_openid_redirect(client)

    # 1.7 验证登录状态
    resp = client.get("https://www.natfrp.com/cgi/v4/user/info")
    user_info = resp.json()

    if "name" not in user_info and "id" not in user_info:
        crack.close()
        raise RuntimeError(f"登录验证失败: {user_info}")

    username = user_info.get("name", "unknown")
    print(f"  ✓ 登录成功! 用户: {username}")

    crack.close()
    return client


def login_with_redirects() -> httpx.Client:
    """
    纯 HTTP 登录流程 (手动处理重定向)
    """
    print("[1/3] 正在登录 ...")

    client = _create_client(follow_redirects=False)
    _prime_openid_session(client)

    # 1.1 获取 OpenID 的 GeeTest 配置
    print("  获取验证码配置 ...")
    resp = client.get(
        "https://openid.13a.com/cgi/captcha?login",
        headers={"referer": "https://openid.13a.com/login", **OPENID_AJAX_HEADERS},
    )
    captcha_data = resp.json()
    if not captcha_data.get("success"):
        raise RuntimeError(f"获取验证码配置失败: {captcha_data}")

    gt = captcha_data["message"]["gt"]
    challenge = captcha_data["message"]["challenge"]
    print(f"  GT: {gt[:16]}...  Challenge: {challenge[:16]}...")

    # 1.2 第一轮 GeeTest 交互，浏览器登录流在这里就拿到 validate
    print("  执行登录验证码握手 ...")
    validate = None
    crack = None
    for round_no in range(1, 7):
        if round_no > 1:
            # 上一轮返回 click（需要识图）：换一张 challenge 重试
            print(f"  [重试 {round_no}/6] 换取新的验证码 challenge ...")
            resp = client.get(
                "https://openid.13a.com/cgi/captcha?login",
                headers={"referer": "https://openid.13a.com/login", **OPENID_AJAX_HEADERS},
            )
            challenge = resp.json()["message"]["challenge"]
        crack = GeeTestCrack(gt, challenge, MOUSE_PATH_FILE, referer="https://openid.13a.com/")
        crack.get_type()
        crack.get_c_s()
        ajax_result = crack.ajax()
        print(f"  ajax 返回: {json.dumps(ajax_result, ensure_ascii=False)[:200]}...")
        validate = ajax_result.get("validate")
        if ajax_result.get("result") == "success" and validate:
            print("  ✓ 验证码通过（协议握手直接通过，无需识图）")
            break
        if ajax_result.get("result") == "click":
            if CAPTCHA_API_KEY:
                print("  命中点选验证码，交由视觉模型识别 ...")
                validate = _solve_click_captcha(crack)
                if validate:
                    break
            else:
                print("  命中点选验证码（需要识图），未配置识图能力，换一张重试 ...")
                crack.close()
                crack = None
                continue
        crack.close()
        crack = None
        if not validate:
            time.sleep(1)

    if not validate or not crack:
        raise RuntimeError("登录验证码握手多轮重试仍未拿到 validate")

    # 1.3 POST 登录
    print("  提交登录 ...")
    login_data = {
        "username": USERNAME,
        "password": PASSWORD,
        "geetest_id": challenge,
        "geetest_challenge": challenge,
        "geetest_validate": validate,
        "geetest_seccode": f"{validate}|jordan",
    }
    resp = client.post(
        "https://openid.13a.com/cgi/password/login",
        data=login_data,
        headers={
            "referer": "https://openid.13a.com/login",
            "content-type": "application/x-www-form-urlencoded; charset=UTF-8",
            **OPENID_AJAX_HEADERS,
        },
    )

    # 1.4 完成 OpenID -> natfrp 跳转桥接
    _follow_openid_redirect(client)

    # 1.5 验证登录
    resp = client.get("https://www.natfrp.com/cgi/v4/user/info")
    user_info = resp.json()

    if "name" not in user_info and "id" not in user_info:
        crack.close()
        raise RuntimeError(f"登录验证失败: {user_info}")

    print(f"  ✓ 登录成功! 用户: {user_info.get('name', 'unknown')}")
    crack.close()
    return client


# ── 步骤 2: 签到 ──────────────────────────────────────────────

def check_sign_status(client: httpx.Client) -> dict:
    """检查签到状态"""
    resp = client.get("https://www.natfrp.com/cgi/v4/user/info")
    return resp.json()


def sign_in(client: httpx.Client) -> bool:
    """
    签到流程:
    1. 获取签到的 GeeTest 配置
    2. 破解验证码
    3. AI 识别九宫格
    4. POST 签到
    """
    print("[2/3] 正在签到 ...")

    # 2.1 检查是否已签到
    user_info = check_sign_status(client)
    print(f"  用户信息: {json.dumps(user_info, ensure_ascii=False)[:200]}...")

    sign_info = user_info.get("sign", {})
    if sign_info.get("signed"):
        print(f"  今天已经签到过了! 连续签到 {sign_info.get('days', '?')} 天")
        return True

    # 2.2 获取签到 GeeTest 配置并握手（握手通过则无需识图；遇到点选则换一张重试）
    print("  获取签到验证码配置 ...")
    validate = None
    challenge = None
    crack = None
    for round_no in range(1, 7):
        resp = client.get("https://www.natfrp.com/cgi/v4/user/sign?gt")
        try:
            geetest_data = resp.json()
        except Exception:
            # 可能返回 JSONP 或其他格式
            print(f"  签到 GeeTest 响应: {resp.text[:200]}...")
            import re
            match = re.search(r"\((.+)\)", resp.text, re.DOTALL)
            if match:
                geetest_data = json.loads(match.group(1))
            else:
                raise RuntimeError(f"无法解析签到 GeeTest 数据: {resp.text[:200]}")

        if "gt" not in geetest_data:
            raise RuntimeError(f"签到 GeeTest 数据格式异常: {geetest_data}")

        gt = geetest_data["gt"]
        challenge = geetest_data["challenge"]
        print(f"  [第 {round_no}/6 轮] GT: {gt[:16]}...  Challenge: {challenge[:16]}...")

        crack = GeeTestCrack(gt, challenge, MOUSE_PATH_FILE, referer="https://www.natfrp.com/user/")
        crack.get_type()
        crack.get_c_s()
        ajax_result = crack.ajax()
        print(f"  ajax 返回: {json.dumps(ajax_result, ensure_ascii=False)[:200]}...")

        if ajax_result.get("result") == "success" and ajax_result.get("validate"):
            validate = ajax_result["validate"]
            print("  ✓ 签到验证通过（协议握手直接通过，无需识图）")
            break

        if ajax_result.get("result") == "click":
            # 九宫格点选：优先视觉模型，失败再退回本地 MobileNet
            print("  命中点选验证码，识别九宫格 ...")
            pic_type, pic_url = crack.get_pic(0)
            print(f"  验证码类型: {pic_type}")
            img_bytes = client.get(pic_url).content
            points = []
            used = ""
            if CAPTCHA_API_KEY:
                points = _vision_nine_grid(img_bytes)
                used = "视觉模型"
            if not points:
                try:
                    points = solve_nine_grid_local(img_bytes)
                    used = "MobileNet"
                except Exception as exc:  # 模型缺失/依赖异常不应中断签到
                    print(f"  ✗ 本地 MobileNet 不可用: {exc}")
                    points = []
            print(f"  识别结果({used}): {points}")
            if not points:
                print("  ✗ 本轮无有效识别结果，换一张重试")
                crack.close()
                crack = None
                time.sleep(1)
                continue
            verify_result = crack.verify(points)
            print(f"  验证结果: {json.dumps(verify_result, ensure_ascii=False)[:200]}")
            if verify_result.get("status") == "success" and verify_result.get("data", {}).get("result") == "success":
                validate = verify_result["data"]["validate"]
                print(f"  ✓ 验证码通过（{used}）")
                break

        crack.close()
        crack = None
        time.sleep(1)

    if crack:
        crack.close()

    if not validate:
        raise RuntimeError("签到验证码多轮重试仍未拿到 validate")

    # 2.5 POST 签到
    print("  提交签到 ...")
    sign_data = {
        "geetest_challenge": challenge,
        "geetest_validate": validate,
        "geetest_seccode": f"{validate}|jordan",
    }
    sign_headers = dict(COMMON_HEADERS)
    sign_headers["content-type"] = "application/x-www-form-urlencoded"
    sign_headers["referer"] = "https://www.natfrp.com/user/"

    resp = client.post(
        "https://www.natfrp.com/cgi/v4/user/sign",
        data=sign_data,
        headers=sign_headers,
    )
    sign_result = resp.json()
    print(f"  签到响应: {json.dumps(sign_result, ensure_ascii=False)}")

    if isinstance(sign_result, str):
        # API 直接返回成功消息字符串
        return True
    return sign_result.get("status") == "success" or sign_result.get("code") == 0


# ── 验证码识别（多模态视觉模型）──────────────────────────────

NINE_PROMPT = (
    "这是极验(GeeTest)的九宫格点选验证码。\n"
    "图片最下方、左侧那个独立的小图案是【参考图标】，代表要找的目标物品（线条简笔画）。\n"
    "图片上方是 3 行 × 3 列的格子，每个格子里是一张物品的真实照片。\n"
    "任务：找出所有与参考图标属于同一种物品的格子。\n"
    "要点：\n"
    "1. 参考图标是简笔画，格子里的物品是真实照片，形状、角度、颜色、背景都可能不同；\n"
    "2. 只按「物品类别」判断，例如参考图标是鹿的简笔画，那么所有鹿的照片都算匹配；\n"
    "3. 不要选长相不同类但风格相似的格子，也不要把参考图标本身当成格子；\n"
    "4. 匹配的格子可能有 1 到 5 个，必须全部找出。\n"
    "行号：从上到下为 1、2、3。列号：从左到右为 1、2、3。\n"
    "只输出JSON，不要任何解释，格式："
    '{"object":"目标物品名称","cells":[[行,列],[行,列]]}'
)


def _vision_chat(data_url: str, prompt: str, max_tokens: int = 400) -> str:
    """直接 POST 到 OpenAI 兼容端点（支持自签名证书），返回文本内容"""
    payload = {
        "model": CAPTCHA_MODEL,
        "messages": [{
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": data_url}},
            ],
        }],
        "max_tokens": max_tokens,
        "stream": False,
    }
    resp = requests.post(
        f"{CAPTCHA_API_BASE.rstrip('/')}/chat/completions",
        json=payload,
        headers={"Authorization": f"Bearer {CAPTCHA_API_KEY}",
                 "Content-Type": "application/json"},
        timeout=120,
        verify=False,
    )
    if resp.status_code != 200:
        print(f"  ✗ 视觉 API HTTP {resp.status_code}: {resp.text[:200]}")
        return ""
    data = resp.json()
    choices = data.get("choices") or []
    if not choices:
        return ""
    message = choices[0].get("message") or {}
    content = message.get("content")
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts = [p.get("text", "") for p in content
                 if isinstance(p, dict) and p.get("type") == "text"]
        return "\n".join(x for x in parts if x).strip()
    return ""


def _parse_nine_cells(text: str) -> list:
    """把模型输出解析成 GeeTest 需要的 ["列_行", ...]（极验 a 参数是 列_行）"""
    import re as _re

    text = _strip_json_fence(text)
    raw_cells = []
    obj = None

    # 优先解析 JSON 对象
    m = _re.search(r'\{.*\}', text, _re.DOTALL)
    if m:
        try:
            obj = json.loads(m.group())
        except (json.JSONDecodeError, ValueError):
            obj = None
    if isinstance(obj, dict):
        raw_cells = obj.get("cells") or obj.get("points") or []
    elif isinstance(obj, list):
        raw_cells = obj

    # 兜底：从 [行,列] / "行_列" / "r1c2" 这类文本里抠
    if not raw_cells:
        pairs = _re.findall(r'\[\s*([1-3])\s*,\s*([1-3])\s*\]', text)
        if pairs:
            raw_cells = [[int(a), int(b)] for a, b in pairs]
        else:
            pairs = _re.findall(r'([1-3])[_\-,\s]+([1-3])', text)
            if pairs:
                raw_cells = [[int(a), int(b)] for a, b in pairs]

    points = []
    for cell in raw_cells:
        row = col = None
        if isinstance(cell, (list, tuple)) and len(cell) >= 2:
            row, col = int(cell[0]), int(cell[1])
        elif isinstance(cell, str):
            nums = _re.findall(r'[1-3]', cell)
            if len(nums) >= 2:
                row, col = int(nums[0]), int(nums[1])
        if row is None or not (1 <= row <= 3 and 1 <= col <= 3):
            continue
        # 极验 a 参数 = 列_行
        point = f"{col}_{row}"
        if point not in points:
            points.append(point)

    if obj and isinstance(obj, dict) and obj.get("object"):
        print(f"  目标物品: {obj['object']}")
    return points


def _vision_nine_grid(img_bytes: bytes) -> list:
    """用多模态模型识别九宫格，返回 ["列_行", ...]"""
    if not CAPTCHA_API_KEY:
        return []
    import base64 as _b64
    data_url = "data:image/png;base64," + _b64.b64encode(img_bytes).decode()
    text = _vision_chat(data_url, NINE_PROMPT)
    if not text:
        print("  ✗ 视觉模型未返回内容")
        return []
    print(f"  视觉模型输出: {text[:300]}")
    return _parse_nine_cells(text)


def _recognize_captcha(image_url: str, pic_type: str) -> list:
    """
    调用多模态 AI 识别验证码图片（九宫格/点选）
    关键：必须先下载图片转 base64 再发给 AI（外部 URL 可能无法被 AI 端点加载）
    返回点击坐标列表，格式为 ["col_row", ...]
    """
    if not CAPTCHA_API_KEY:
        print("  ✗ 未配置 CAPTCHA_API_KEY")
        return []

    # 下载图片并转 base64 data URL
    import base64 as _b64
    img_resp = requests.get(image_url, timeout=30,
                            headers={"User-Agent": COMMON_HEADERS["user-agent"],
                                     "Referer": "https://www.natfrp.com/"})
    img_data = _b64.b64encode(img_resp.content).decode()
    data_url = f"data:image/jpeg;base64,{img_data}"

    if pic_type == "nine":
        return _vision_nine_grid(img_resp.content)

    else:
        # icon/space 类型验证码 (点选文字/图标位置)
        prompt = (
            '这是一个点选验证码。请识别图中需要点击的目标文字或图标，'
            '并返回每个目标的大致坐标位置。输出格式为JSON列表：'
            '[{"x": 100, "y": 200}, ...]。坐标原点在左上角。'
            '只输出JSON，不要其他文字。'
        )
        result_text = _strip_json_fence(_vision_chat(data_url, prompt))
        if not result_text:
            print("  ✗ AI 未返回内容")
            return []
        print(f"  AI 识别原始结果: {result_text}")

        try:
            coords = json.loads(result_text)
            if isinstance(coords, dict):
                coords = coords.get("coordinates", coords.get("points", []))
            points = []
            for c in coords:
                if isinstance(c, dict):
                    if "x" in c and "y" in c:
                        points.append(f"{c['x']}_{c['y']}")
                    elif "point_2d" in c:
                        pt = c["point_2d"]
                        points.append(f"{pt[0]}_{pt[1]}")
            return points
        except (json.JSONDecodeError, KeyError, TypeError, IndexError):
            print("  ✗ 坐标解析失败")
            return []


# ── 主流程 ────────────────────────────────────────────────────

def main():
    if not USERNAME or not PASSWORD:
        print("⏭  未配置 NATFRP_USERNAME / NATFRP_PASSWORD，跳过 natfrp 签到")
        return 0
    if not CAPTCHA_API_KEY:
        print("ℹ  未配置视觉模型密钥 VISION_API_KEY，使用「协议握手 + 换图重试」模式运行")
        print("   （极验握手多数情况可直接通过；若连续命中点选验证码，本轮会失败并留待下一时隙重试）")

    start_time = time.time()

    try:
        # 步骤 1: 登录
        client = login_with_redirects()

        # 步骤 2: 签到
        success = sign_in(client)

        # 步骤 3: 验证结果
        print("[3/3] 验证签到结果 ...")
        user_info = check_sign_status(client)
        print(f"  用户信息: {json.dumps(user_info, ensure_ascii=False)[:200]}...")

        elapsed = time.time() - start_time
        if success:
            print(f"\n✓ 签到成功! 耗时: {elapsed:.1f}s")
        else:
            print(f"\n✗ 签到可能失败，请检查。耗时: {elapsed:.1f}s")

        client.close()

    except Exception as e:
        print(f"\n✗ 流程出错: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()

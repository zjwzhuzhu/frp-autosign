# -*- coding: utf-8 -*-
"""探针：实测签到九宫格识别准确率（只做验证码，不提交签到，不消耗当天签到）"""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "natfrp"))

from auto_signin import (  # noqa: E402
    CAPTCHA_API_KEY,
    GeeTestCrack,
    MOUSE_PATH_FILE,
    _vision_nine_grid,
    login_with_redirects,
    solve_nine_grid_local,
)

OUT = Path(__file__).parent / "captcha_probe"
OUT.mkdir(exist_ok=True)

ROUNDS = int(sys.argv[1]) if len(sys.argv) > 1 else 3


def main():
    print("vision key configured:", bool(CAPTCHA_API_KEY))
    client = login_with_redirects()
    ok = 0
    tried = 0
    try:
        for i in range(1, ROUNDS + 1):
            r = client.get("https://www.natfrp.com/cgi/v4/user/sign?gt")
            data = r.json()
            gt, ch = data["gt"], data["challenge"]
            print(f"\n===== 第 {i}/{ROUNDS} 轮 gt={gt[:12]}... ch={ch[:12]}... =====")
            crack = GeeTestCrack(gt, ch, MOUSE_PATH_FILE, referer="https://www.natfrp.com/user/")
            try:
                crack.get_type()
                crack.get_c_s()
                aj = crack.ajax()
                print("ajax:", json.dumps(aj, ensure_ascii=False)[:150])
                if aj.get("result") == "success":
                    print("  本轮握手直接通过（无图）")
                    continue
                if aj.get("result") != "click":
                    print("  非 click 类型，跳过")
                    continue
                tried += 1
                pic_type, pic_url = crack.get_pic(0)
                img = client.get(pic_url).content
                p = OUT / f"live_{i}.png"
                p.write_bytes(img)
                print(f"  pic_type={pic_type} saved={p.name} ({len(img)} bytes)")

                vp = _vision_nine_grid(img)
                print(f"  视觉模型: {vp}")
                lp = solve_nine_grid_local(img)
                print(f"  MobileNet: {lp}")

                if vp:
                    res = crack.verify(vp)
                    good = (res.get("status") == "success"
                            and res.get("data", {}).get("result") == "success")
                    print(f"  视觉模型验证: {json.dumps(res, ensure_ascii=False)[:160]} -> {'PASS' if good else 'FAIL'}")
                    if good:
                        ok += 1
            finally:
                crack.close()
                time.sleep(1)
    finally:
        client.close()
    print(f"\n结果: 出图 {tried} 轮，通过 {ok} 轮")


if __name__ == "__main__":
    main()

# FRP 自动签到（88frp + natfrp）

每天自动完成两个内网穿透服务商的签到：

| 站点 | 方式 | 状态 |
|---|---|---|
| 88frp.com | 纯 HTTP（账号密码登录 + 签到接口） | ✅ 全自动 |
| natfrp.com（SakuraFrp） | 纯 HTTP + GeeTest 协议握手（**无需视觉模型**），命中点选验证码时自动换图重试 | ✅ 全自动 |

## 一、配置 Secrets

在仓库 Settings → Secrets and variables → Actions 中添加：

- `FRP88_USERNAME`：88frp 用户名
- `FRP88_PASSWORD`：88frp 密码
- `NATFRP_USERNAME`：natfrp 用户名
- `NATFRP_PASSWORD`：natfrp 密码

**可选（提高点选验证码通过率，不配也能跑）**
- `VISION_API_BASE` / `VISION_API_KEY` / `VISION_MODEL`：OpenAI 兼容视觉模型，
  仅在极验返回「点选/九宫格」图片时才会调用；未配置时走「换一张重试」。

> natfrp 的 GeeTest 走的是协议握手（AES/RSA 加密的 `w` 参数 + 鼠标轨迹 + 指纹字段），
> 实测握手阶段服务端多数情况直接返回 `success` 并下发 validate，**无需识图即可登录与签到**。
> 少数情况会下发点选图片，此时换新 challenge 重试（最多 6 轮）。

## 二、运行方式

- 定时：每天北京时间 `09:07` / `13:31` / `20:53` 三个非整点窗口（降低 GitHub 调度丢单），
  每次触发前随机等待 1~6 分钟。
- 手动：Actions → FRP Auto Sign-in → Run workflow。
- 已签到时会输出「今日已签到 / 今天已经签到过了」并正常结束。

## 三、接口说明（88frp）

```
POST https://api.88frp.com/api/auth/login
  body: {"username": "...", "password": "..."} → data.token
POST https://api.88frp.com/api/domain/value-added-rights/signIn
  header: Authorization: Bearer <token>
```

## 四、natfrp 实现来源

`natfrp/` 目录移植自 MIT 协议项目 [claaudy/sakurafrp-auto-sign](https://github.com/claaudy/sakurafrp-auto-sign)
（GeeTest v3 协议逆向 + 鼠标轨迹编码 + OpenID 跳转拼接），详见 `natfrp/NOTICE.md`。

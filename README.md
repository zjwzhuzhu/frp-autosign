# FRP 自动签到（88frp + natfrp）

每天自动完成两个内网穿透服务商的签到：

| 站点 | 方式 | 状态 |
|---|---|---|
| 88frp.com | 纯 HTTP（账号密码登录 + 签到接口） | ✅ 全自动 |
| natfrp.com（SakuraFrp） | 纯 HTTP + GeeTest 极验协议 + AI 视觉识别 | ⚠ 需要视觉模型密钥 |

## 一、配置 Secrets

在仓库 Settings → Secrets and variables → Actions 中添加：

**88frp（必需）**
- `FRP88_USERNAME`：88frp 用户名
- `FRP88_PASSWORD`：88frp 密码

**natfrp（可选，缺任一项会自动跳过并输出提示）**
- `NATFRP_USERNAME`：natfrp 用户名
- `NATFRP_PASSWORD`：natfrp 密码
- `VISION_API_BASE`：OpenAI 兼容接口地址（如 `https://api.openai.com/v1`）
- `VISION_API_KEY`：视觉模型 API Key
- `VISION_MODEL`：支持图片输入的模型名（如 `gpt-4o`、`doubao-1.5-vision-pro`、`claude-sonnet-4`）

> natfrp 的登录与每次签到都强制 GeeTest 极验（九宫格点选/滑动），
> 纯协议无法绕过图片内容识别，因此必须配一个可用的**多模态视觉模型**。
> 未配置时工作流仍会正常跑 88frp，natfrp 步骤打印「跳过」并保持成功状态。

## 二、运行方式

- 定时：每天北京时间 `09:07` / `13:31` / `20:53` 三个非整点窗口（降低 GitHub 调度丢单），
  每次触发前随机等待 1~6 分钟。
- 手动：Actions → FRP Auto Sign-in → Run workflow。
- 已签到时会输出「今日已签到」并正常结束。

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

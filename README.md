# FRP 自动签到（88frp + natfrp）

每天自动完成两个内网穿透服务商的签到：

| 站点 | 方式 | 状态 |
|---|---|---|
| 88frp.com | 纯 HTTP（账号密码登录 + 签到接口） | ✅ 全自动 |
| natfrp.com（SakuraFrp） | 纯 HTTP + GeeTest 协议握手；命中九宫格时用视觉模型识图 | ✅ 全自动 |

## 一、配置 Secrets

在仓库 Settings → Secrets and variables → Actions 中添加：

- `FRP88_USERNAME`：88frp 用户名
- `FRP88_PASSWORD`：88frp 密码
- `NATFRP_USERNAME`：natfrp 用户名
- `NATFRP_PASSWORD`：natfrp 密码
- `VISION_API_BASE` / `VISION_API_KEY` / `VISION_MODEL`：OpenAI 兼容的多模态模型端点
  （签到遇到九宫格时调用；例如 `https://xxx/v1` + `sk-...` + `deepseek-v4.1-flash`）。
  **不配置也不会中断**：会退回本地 MobileNet 兜底识图，或换一张图重试。

> natfrp 的 GeeTest 走的是协议握手（AES/RSA 加密的 `w` 参数 + 鼠标轨迹 + 指纹字段）。
> 握手阶段服务端有时直接返回 `success` 并下发 validate（无需识图）；
> 多数情况会下发 **nine 九宫格**，需要识别「底部参考简笔画对应的物品」并把 3×3 中同类物品的格子全部点选。

### 九宫格识别的两个坑（重要）

1. **坐标顺序**：极验 `a` 参数是 **`列_行`**（列在前、行在后），例如左上角是 `1_1`、中上是 `2_1`、左中是 `1_2`。
   模型按「第几行第几列」推理最自然，代码里 `_parse_nine_cells()` 负责把 `[行,列]` 换算成 `列_行`。
   顺序写反会导致识别结果完全正确却始终 `result: fail`。
2. **必须真的调视觉模型**：`VISION_API_KEY` 缺失时脚本会静默退回本地 MobileNet，
   而 MobileNet（ImageNet 分类）在九宫格上基本是乱猜——CI 日志会出现「识别结果(MobileNet)」。
   排查时先确认日志里是「识别结果(视觉模型)」。

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

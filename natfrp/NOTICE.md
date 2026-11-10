# 第三方代码来源声明

`auto_signin.py`、`geetest_crack.py`、`mousepath.json` 移植自：

- 项目：https://github.com/claaudy/sakurafrp-auto-sign
- 作者：Leon
- 许可证：MIT License

原始实现完成 SakuraFRP (natfrp.com) 的纯 HTTP 登录与每日签到，
包含 GeeTest v3 验证码协议逆向（AES-CBC/RSA 加密的 w 参数、自定义 base64、
鼠标轨迹编码、浏览器指纹字段）与 OpenID OAuth 跳转桥接。

本仓库仅做少量适配：将入口改为环境变量读取（`NATFRP_USERNAME` /
`NATFRP_PASSWORD` / `VISION_API_*`），并在缺少视觉模型密钥时优雅跳过。

MIT License 原文见上游仓库 LICENSE 文件。

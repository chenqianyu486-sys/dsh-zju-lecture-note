---
name: zju-lecture-summarizer-help
description: 浙大智云课堂插件的登录辅助与故障排查（401/403、登录态、代理、Typst/PDF、工具开关）。用户输入 /zju-lecture-summarizer-help 或询问插件为何不可用时使用。
---

# 智云课堂插件：登录辅助与查错

这是一个**排查命令**，不是讲义生成命令。先判断用户要解决什么，再按证据排查；不要一上来抓字幕、写讲义或改配置。

## 隐私红线（优先于一切）

- 不要要求用户把 Cookie、`_token`、Bearer、密码或浏览器数据库内容粘贴到对话。
- 不要在回复、命令、文件或日志里复述任何凭据；如果用户已经贴出，提醒他撤回并重新登录/轮换，不要重复其中内容。
- 不要读取浏览器历史、密码或其他网站 Cookie；登录态只允许来自插件既有的本地来源：
  `zju_login` 保存的本机登录态、`ZJU_COOKIE`、`ZJU_COOKIE_FILE` 或本机 Microsoft Edge。
- 不要建议关闭 TLS 校验，也不要把 Cookie / Bearer 发往 `classroom.zju.edu.cn` 之外的主机。
- 不要擅自修改用户环境变量、注册表、浏览器配置或 `~/.dsh`；需要用户操作时，只给最短步骤。
- 诊断结果只描述“可用 / 不可用、来源类别、错误类别、下一步”，不回显值。

## 先确认症状

如果用户没有说明，先问一句：是生成讲义、字幕 401/403、PDF、投影、填空笔记，还是找不到命令/工具？

## 诊断顺序

1. 先运行 `zju_doctor`（默认不读取登录态），确认 Python、Typst、字体、Typst 包和当前模块开关。
2. 只有问题涉及登录或字幕 401/403 时，再运行 `zju_doctor(login=true)`。
   它只报告登录态是否可用、来源类别与 Bearer 是否可用，不返回值。
3. 根据结果分流，不要跳过证据直接猜原因。

### A. 字幕 401/403

- 插件先匿名请求；401/403 时自动读取本机登录态并用 Bearer 重试一次。
  **不需要开启「登录辅助」工具**。
- **首选动作：调用 `zju_login(url=<这节课链接>)`**。它会弹出一个独立的
  Edge / Chrome 登录窗口，不碰用户日常浏览器；用户在窗口里正常登录后，
  窗口自动关闭，登录态安全保存到本机（Windows DPAPI；macOS / Linux 为 0600 文件）。
  不需要开发者工具，不需要用户手工复制 Cookie，也不需要修改环境变量。
- 调用前先告诉用户：「会弹出一个独立登录窗口，请在里面完成登录；成功后窗口会自动关闭。」
  登录成功后重试字幕一次；**最多调用 `zju_login` 两次**，不要无限弹窗。
- 按 `zju_login` 返回的 `reason` 给一条动作：
  - `no_browser`：本机没有 Edge / Chrome / Chromium。安装浏览器后重试；
    无图形界面的服务器改用 `ZJU_COOKIE_FILE`。
  - `devtools_blocked` / `launch_failed`：企业策略或安全软件拦截了本机调试端口。
    重试一次；仍失败改用 `ZJU_COOKIE_FILE`。
  - `timeout` / `closed`：用户没有在时限内完成登录，或提前关了窗口；重试一次即可。
  - `save_failed`：本次会话可用，但重启后需要重新登录。检查用户目录写权限；
    或改用 `ZJU_COOKIE_FILE`。
  - `bad_url`：只传 `https://*.zju.edu.cn` 的课堂链接，不要传其他站点。
- 如果 `zju_doctor(login=true)` 仍报 `abe` / `decrypt_failed` / `locked` / `no_rows`：
  **不要建议反复退出 Edge**，直接调用 `zju_login`。这些原因只说明「读 Edge 数据库」失败，
  与独立登录窗口无关。
- **高级兜底**（仅当 `zju_login` 不可用，例如无图形界面的服务器）：
  配置 `ZJU_COOKIE_FILE`，文件内只放一行 Cookie 头（含 `_token`），
  不要把文件内容发给模型或贴进对话。`ZJU_COOKIE` / `ZJU_COOKIE_FILE` 存在时优先级最高，
  配错会挡住 `zju_login`；指导用户检查或移除后再重试。
- 若登录态显示可用但 401/403 仍存在：请用户确认官网同一账号能看同一节课的字幕，
  然后重新调用 `zju_login`；**不要直接归因校园网，不要更换后端或主机**。
- 若接口返回业务错误（code≠0）或列表为空：检查 `sub_id`、课程权限、字幕是否已生成。

### B. 找不到命令或工具

- `/zju-lecture-summarizer` 生成讲义；`/zju-lecture-summarizer-help` 是本排查命令；
  `/zju-lecture-summarizer-login` 只负责打开登录窗口 / 清除本机登录态。
- 默认注册 7 个核心工具（含 `zju_login` 与 `zju_doctor`）；投影（`enableSlides`）、
  填空笔记（`enableStudyNotes`）、登录辅助工具（`enableLoginTools`）是独立可选开关。
- 修改设置后必须**完全重启 DeepSeek Harness**，当前会话不会热加载新工具集。
- 字幕鉴权与 `zju_login` 都不受 `enableLoginTools` 影响，不要把“登录辅助关闭”误判成字幕不可用。
- 用户想清除本机登录态时，调用 `zju_login(clear=true)`，不要手工删文件。

### C. PDF / Typst

- 先跑 `zju_doctor`；缺少 Typst 时用 `zju_doctor(install=true)`。
- 检查 `renderPdf` 是否开启；Markdown 写入成功而 PDF 失败时，先交付 Markdown。
- 不要让用户关闭证书校验或从非官方来源安装 Typst。

### D. 代理 / 证书

- 查看 `HTTPS_PROXY` / `HTTP_PROXY` / `NO_PROXY`；代理 URL 的 userinfo 在诊断中已掩码。
- 不要在对话里展示完整代理凭据；不要建议关闭 TLS。
- 代理导致的问题优先让 `classroom.zju.edu.cn` 直连，或设置 `NO_PROXY`。

### E. 投影 / 填空笔记

- 投影抓取需要 `enableSlides` 与可用登录态；登录态问题同样走 `zju_login`。
- 填空笔记需要 `enableStudyNotes` 与本机 Typst。
- 两个模块互不依赖；失败时先确认对应开关与 `zju_doctor`，不要混在一起猜。

## 回复格式

- 先给一句结论，再分「已确认」「还需要你确认」「下一步」。
- 最多给 3 个可执行步骤；需要用户操作时，说明完成后回复什么（例如“已登录 Edge，重试”）。
- 没有工具结果时，不要声称“已经验证”或“已经修复”。
- 报告问题时可让用户提供：操作系统、dsh 版本、插件版本、工具名、脱敏后的错误文本；
  **不要**要求 Cookie、token、完整 HAR、课程个人数据或代理凭据。

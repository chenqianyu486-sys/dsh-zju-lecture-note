# 浙大智云课堂讲义插件（ZJU Lecture Agent Plugin）
由 [`nzw806/zju-lecture-summerizer-`](https://github.com/nzw806/zju-lecture-summerizer-) 改编的 DeepSeek Harness 原生插件，提供开箱即用的体验。
面向 **DeepSeek Harness（dsh）** 与任意 **MCP 宿主**（Claude Code / Cursor / Cline / MiniMax Code…）。
<img width="2288" height="916" alt="image" src="https://github.com/user-attachments/assets/a7c62c79-bb7a-4770-9893-859f75692059" />

## 开始使用

- 安装 DeepSeek Harness。
- 进入插件 → 添加插件，填入 npm 包名 `dsh-zju-lecture-note` 或仓库链接 https://github.com/chenqianyu486-sys/dsh-zju-lecture-note 。
- 安装并启用插件。
- 首次使用**不需要配置 Cookie**：字幕被拒时，Agent 会调用 `zju_login` 打开独立登录窗口；你在窗口里正常登录，成功后窗口自动关闭并按系统能力保存登录态。也可主动输入 `/zju-lecture-summarizer-login`。
- 新会话输入 `/zju-lecture-summarizer` 总结课程；`/zju-lecture-summarizer-login` 管理登录；`/zju-lecture-summarizer-help` 排查 401/403 与依赖问题。例：
```text
/zju-lecture-summarizer 帮我总结课程内容 https://classroom.zju.edu.cn/livingroom?course_id=87517&sub_id=1988617&tenant_code=112
```
```text
/zju-lecture-summarizer-help 帮我解决当前无法使用的问题
```

> 把浙大智云课堂（`classroom.zju.edu.cn`）的课程回放，变成一份**能直接复习的讲义**：
> - Agent 生成结构化 Markdown ，并按内置排版器在本机排成易读的 PDF 讲义，单次总结成本约 ￥0.3，耗时约 1.5min 。
> - 字幕先匿名；401/403 时自动使用本机登录态重试一次。仍不可用时插件会打开独立登录窗口，你正常登录即可；登录态按系统能力保存在本机（Windows DPAPI；macOS/Linux 0600），不回显、不进入对话、不保存密码。
> - 核心只用 Python 标准库；PDF 排版所需的 Typst、中文字体与 Typst 包由插件自带或首次使用时自动准备。
> - **非官方工具**：与浙江大学及其「智云课堂」平台无隶属关系，也未获其背书。

## 功能特色

- **一句话出讲义**：给回放链接或 `sub_id`，Agent 抓字幕、写 Markdown、修公式、校验、命名，一次完成。
- **便捷获取登录态**：缺登录态导致 401/403 时自动打开独立登录窗口，登录后保存在本机，无需额外使用开发者工具。
- **装完即用**：缺少 Typst 时首次排版自动准备（可关）；中文字体与 Typst 包随插件分发，填空笔记离线也能编译。
- **自动 PDF**：使用内置脚本在本地排同名 PDF，无需额外 token 花销；PDF 失败不影响 Markdown 讲义。
- **填空式复习**：可选「填空式学习笔记」——基于 Typst scholia 模板排版的填空式学习笔记；配色与段落规范由本项目定义。
- **隐私优先**：常规工具不要求或读取 Cookie 参数，登录态不回显，Cookie/Bearer 输出脱敏；敏感文件拒绝；TLS 永不降级。当前版本仍有已知安全缺口，见 [SECURITY.md](SECURITY.md)。

PDF 渲染效果预览：
<img width="1098" height="1472" alt="image" src="https://github.com/user-attachments/assets/610d5f5d-5dd0-45bb-abfc-924e629132da" />

## 安装

### 1. DeepSeek Harness（dsh）

从 npm 安装（推荐）：

```bash
dsh plugin --profile desktop add dsh-zju-lecture-note
```

或直接从 GitHub 仓库安装（跟随最新提交）：

```bash
dsh plugin --profile desktop add github:chenqianyu486-sys/dsh-zju-lecture-note
```

- `desktop` profile 请用 **dsh 自带的 dsh 命令**（`resources/runtime/cli/bin/dsh.cmd`），
  不要用 npm 全局安装的 `dsh`。
- **装完 / 更新后完全重启 DeepSeek Harness**（不是刷新页面）：设置页的
  「浙大智云课堂讲义」一栏与左栏入口要重启后才会出现。
- 不要只解压 zip 让 dsh 加载；请用 npm 包名、`github:` 或 `file:` 方式安装。

装好后直接说：

> 帮我把这节课整理成讲义：https://classroom.zju.edu.cn/livingroom?course_id=58133&sub_id=123456

### 2. 任意 MCP 宿主

本仓库自带 stdio MCP Server，配置里只要一个 PATH 上的 `node`：

```json
{
  "mcpServers": {
    "zju-lecture": {
      "type": "stdio",
      "command": "node",
      "args": ["/绝对路径/dsh-zju-lecture-note/server.mjs"],
      "timeout": 600000
    }
  }
}
```

Claude Code 一行接入：

```bash
claude mcp add zju-lecture node /绝对路径/dsh-zju-lecture-note/server.mjs
```

### 3. 其它入口

```bash
# MiniMax Code 插件包
python tools/build_plugin.py --install --zip

# 命令行
python -m zju_lecture.cli login "<回放链接>"
python -m zju_lecture.cli parse "<回放链接>"
python -m zju_lecture.cli fetch 123456 --format min -o 字幕.txt
python -m zju_lecture.cli courseware ./课件.pptx
python -m zju_lecture.cli slides "<回放链接>" --download
```

## 怎么用

对 Agent 说一句话就够了：

> 帮我把这节课整理成讲义：<回放链接>，重点讲后半节的样条插值。

> 刚才那份讲义，把第 3 节的公式再推导一遍，并出 3 道自测题。

- 讲义默认写在工作区根目录，文件名由 Agent 按「上课日期 + 本节内容」起名
  （`知识总结-2026-10-28-复变函数-保角映射.md`），PDF 同名同目录。
- 同名讲义默认拒绝覆盖，要覆盖请明确说「覆盖」。
- 讲义不进 Git：`.gitignore` 已挡掉任意层级的 `知识总结*.md` 与 `/notes/`。
- 字幕先匿名；401/403 时自动用本机登录态重试一次。一次只抓一节课，不要批量抓取。

### 阅读版 PDF

讲义写完会自动在同目录生成同名 PDF，不需要额外操作。PDF 失败不影响 Markdown，
只少这一份文件；也可以关闭自动排版，只交付 Markdown。需要给旧讲义补 PDF 时，
让 Agent 重新检查并排版即可。

### 填空式学习笔记（可选）

打开「填空式学习笔记」后，可以直接让 Agent 出一版填空笔记：把已完成的讲义变成
一份可动手填写的复习 PDF（另附逐页图片）。它基于 Typst scholia 模板排版；
配色与段落规范由本项目定义。哪里挖空、哪些内容进方框属于内容判断，
插件只负责搬运与排版。

### 投影截图（可选，默认关闭）

打开「抓取 PPT 投影截图」后，可把课堂投影截图作为讲义的视觉补充（需要浙大登录态）。
投影接口只返回截图，没有文字层或 OCR；需要幻灯片原文请提供原始 `.pptx`。

## 设置

设置有两个入口，内容与配置完全一致：

- **设置 → 左侧导航「浙大智云课堂讲义」**；
- **主界面左栏「智云讲义」**，点开在主区域显示同一页。

设置按「核心链路 → 阅读输出 → 环境 → 主动回忆 → 课堂投影 → 登录辅助 → 高级」分组，
并提供三枚预设：**省 Token / 复习模式 / 全功能**。

| 设置 | 作用 | 默认 |
| :--- | :--- | :--- |
| 自动排版 PDF 讲义 | 写完讲义后自动生成同名 PDF | 开 |
| 自动安装 Typst | 缺少排版引擎时自动准备（约 20 MB） | 开 |
| Typst 可执行文件 | 留空自动查找；填写绝对路径可固定版本 | 留空 |
| Typst 下载镜像 | 自动安装时的 GitHub 镜像前缀 | 留空 |
| 填空式学习笔记 | 额外提供填空笔记 PDF | 关 |
| 抓取 PPT 投影截图 | 获取课堂投影截图（需登录态） | 关 |
| 把截图引用进讲义 | 是否把截图插入讲义（需先开启上一项） | 关 |
| 视频直链与登录态工具 | 额外的登录辅助工具；不影响字幕与一键登录 | 关 |
| Python 解释器 | 留空优先用 dsh 自带 Python；可指定绝对路径 | 留空 |
| 工具超时（毫秒） | 普通工具的超时；PDF / 登录等有更高下限 | 120000 |
| 注册随包 Skill | 关闭后不注册讲义工作流与用户命令，工具仍可用 | 开 |

保存后**立即生效**：插件会重新同步工具、Skill、系统提示词与 Python 子进程，Agent 在下一轮就能读到新配置，不需要重启。
只有首次安装或更新插件本身才需要完全重启 DeepSeek Harness。环境变量与开关分层见
[技术细节](docs/technical.md#3-工具与开关分层)。

## 常见问题

**设置里找不到「浙大智云课堂讲义」一栏？**
完全重启 DeepSeek Harness；刷新页面或只重装插件都不够。

**返回 `PDF 跳过: …`？**
Markdown 已经正常写入，只是 PDF 没排出来。让 Agent 跑一次 `zju_doctor` 查看缺什么；
缺少 Typst 时可让 Agent 安装，或打开设置里的「自动安装 Typst」。

**看不到投影或登录辅助工具？**
它们默认关闭，到设置里打开即可立即生效（Agent 下一轮会读到新工具）；如果刚安装或更新过插件，
仍需完全重启 dsh。一键登录 `zju_login` 始终可用，字幕鉴权也不依赖登录辅助开关。

**只解压 zip 启用报错？**
请用 npm 包名、`github:` 或 `file:` 方式安装，不要直接让 dsh 加载解压目录。

**市场安装报 `connection to github.com timed out after 5000ms`？**
这是安装前的网络连通性检查超时。优先改用上面的 npm 命令安装；必须走 GitHub 源时，
先确认 git 能正常访问 GitHub。

**字幕抓取失败（401/403 / 证书 / 代理）？**
让 Agent 调用 `zju_login`（或输入 `/zju-lecture-summarizer-login`）打开独立登录窗口，
正常登录后会自动重试一次。不要输入开发者工具复制的 Cookie，也不要反复重试。
只有无图形界面的服务器才需要本地 Cookie 文件兜底；证书校验不会降级，
更多说明见 [SECURITY.md](SECURITY.md)。

## 隐私与安全

> **当前安全状态（2026-11-07）**：2026-11-06 安全审查发现的 9 项问题已全部修复，
> 包括多会话工作区隔离、截图重定向/SSRF、工作区外回写、镜像 URL 脱敏、隐私扫描器输出、
> POSIX 临时文件与备份权限、参数白名单、封面注入与资源上限。逐条修复与边界见
> [SECURITY.md](SECURITY.md) 第 7 / 9 / 10 节。

- **登录态不是正常工具参数**：字幕 / 投影 / 视频直链 / 读 Cookie 工具不要求 Cookie；
  登录态只能由 `zju_login`、本地配置或本机 Edge 提供。工具调用入口会拒绝任何
  未在 schema 中声明的字段，不要把凭据粘进工具调用。
- **登录态落盘、不回显**：`zju_login` 只保存 Cookie（不保存账号密码），
  Windows 用 DPAPI 绑定当前用户，macOS / Linux 是 **0600 权限的明文文件**；
  `zju_login(clear=true, confirm=true)` 会一并删除登录态与独立浏览器配置。
  Cookie / Bearer 输出脱敏，镜像 URL 等诊断也会去掉 userinfo 与签名 query。
- **网络边界**：正常请求只到 `classroom.zju.edu.cn`、`https://*.zju.edu.cn` 截图主机
  与 Typst 官方下载地址；课堂 API 只允许同 origin 重定向。投影截图的每一跳都校验
  浙大域、HTTPS 与私网地址，非浙大目标不跟随；证书校验不降级。
- **本地文件有边界**：课件 / 讲义工具只接受指定扩展名，拒绝凭据、私钥与浏览器数据；
  所有回写（含 `fix=true` 与填空 `mode=patch`）都限制在工作区内；读取工作区外课件
  必须显式传 `allow_outside_workspace=true`，且结果首行会标注。

完整威胁模型与边界见 [SECURITY.md](SECURITY.md)。

## 许可与致谢

本插件以 MIT 许可证发布，改编自 [`nzw806/zju-lecture-summerizer-`](https://github.com/nzw806/zju-lecture-summerizer-)（MIT），
原项目的版权声明保留在 [LICENSE](LICENSE)。

**PDF 排版的上游模板**（特别感谢）：

- [`@preview/scholia`](https://typst.app/universe/package/scholia) **0.1.0**（MIT，© Eric Yang / 杨星宇，
  仓库 [`Eryc123Y/scholia`](https://github.com/Eryc123Y/scholia)）：填空式学习笔记的排版引擎。
  该包及其依赖已随本仓库分发（vendored），逐包保留上游许可；版本与修改记录见
  [`VENDORED.md`](zju_lecture/typst-packages/VENDORED.md)。阅读版讲义使用本项目自研模板，
  视觉上参考其浅色主题，未拷贝源码。
- 其他传递依赖（frame-it / marginalia / theoretic / showybox / noteworthy）同样随包分发。
- 上游 scholia 声明自己是受 [`loom-notes`](https://github.com/Polaris-Aeterna/loom-notes)
  设计启发的独立重写；本仓库未分发它。
- 「scholia」一词仅用于指代所依赖的 Typst 包；本插件与 Eric Yang 无隶属关系，
  也未获其背书。逐条归属见 [ATTRIBUTION.md](ATTRIBUTION.md) 与
  [THIRD_PARTY_NOTICES.md](skills/scholia-notes/THIRD_PARTY_NOTICES.md)。

**随包中文字体**：`Notes Kai SC` 与 `Notes Serif SC` 是霞鹜文楷 / Noto Serif SC 的
GB2312 子集，均为 SIL OFL 1.1，已改名以避免与本机字体冲突；许可文件随字体一起分发。

其他项目：

- [`PeiPei233/zju-learning-assistant`](https://github.com/PeiPei233/zju-learning-assistant)（ZLA，MIT）：
  智云课堂 / 学在浙大 API 流程的原始实现，本插件与参考 CLI 的共同上游。
- [`8eoyw/zju-learning-cli`](https://github.com/8eoyw/zju-learning-cli)（MIT）：投影 PPT 管线的参考，
  本仓库按零第三方依赖重新实现，未拷贝代码。
- [Typst](https://typst.app)（Apache-2.0）：PDF 排版编译器；插件不分发 Typst 二进制，
  缺少时从官方 Release 下载并按固定 SHA256 校验。
- [`certifi`](https://github.com/certifi/python-certifi) 与 Mozilla CA 证书库：随包 `cacert.pem` 的来源。
- 以及为本插件提交 issue、做实地运行反馈、审查代码与文档的同学。

## 文档

| 文档 | 内容 |
| :--- | :--- |
| [docs/technical.md](docs/technical.md) | 技术细节：目录结构、隐私实现、PDF 排版、标记语法、开发测试、发布流程 |
| [CHANGELOG.md](CHANGELOG.md) | 版本历史 |
| [SECURITY.md](SECURITY.md) | 威胁模型、Cookie 生命周期、已知边界 |
| [ATTRIBUTION.md](ATTRIBUTION.md) | 逐文件来源、第三方许可、参考实现边界 |

仅供个人学习使用：只抓取本人有权限访问的回放，Cookie 属个人凭证，不要外传。

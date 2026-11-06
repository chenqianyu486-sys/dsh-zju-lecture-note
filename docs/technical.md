# 技术细节

本文件面向**改代码、审代码、排错**的读者。只想安装和使用请看 [README](../README.md)；
版本历史见 [CHANGELOG](../CHANGELOG.md)。

## 1. 仓库结构与数据流

本仓库既是插件的**能力核心**，也是 **dsh 原生插件包的发布源**：Python 核心、MCP 服务器、
讲义 Skill，以及 dsh 用的 `package.json` / `cordis.patch.yml` / `lib/` 都在这里。

```text
dsh-zju-lecture-note/
├── package.json                   # npm / dsh 插件包清单（包名 dsh-zju-lecture-note）
├── cordis.patch.yml               # dsh bundle patch（把插件插进 cordis）
├── lib/                           # dsh 插件实现（ESM）
│   ├── index.js                   # 插件入口：按开关注册工具 + 内存注册随包 Skill
│   ├── bridge.js                  # 拉起随包 Python 核心（JSON-RPC over stdio）
│   ├── client.js                  # 浏览器半边：设置页 + 左栏「智云讲义」入口
│   ├── tools.js                   # 生成物：dsh 工具定义
│   └── tools.schema.json          # 生成物：工具定义快照（供测试比对）
├── .minimax-plugin/plugin.json    # MiniMax Code（MCode）插件清单
├── zju-lecture.mcp.json           # MCP 服务器定义（stdio → node ./server.mjs）
├── server.mjs                     # 启动器：解析 Python 解释器并拉起 MCP 服务
├── mcp_server.py                  # MCP stdio 服务器（JSON-RPC 2.0，隐私边界在这里）
├── zju_lecture/                   # 核心库（纯标准库）
│   ├── client.py                  # 智云课堂 API 客户端（TLS 校验 + 同域重定向）
│   ├── cookies.py                 # Edge Cookie 读取与安全清理
│   ├── browser_login.py           # 一键登录窗口：CDP 取 Cookie + 安全保存 + 清除
│   ├── security.py                # Cookie 校验 / redactor / 本地文件边界
│   ├── paths.py                   # 工作区与相对路径解析
│   ├── courseware.py              # 课件文本提取（带路径校验）
│   ├── note_lint.py               # 讲义 Markdown 公式规范检查 / 自动修复
│   ├── handout.py                 # 讲义 Markdown → 阅读版 PDF（自动排版）
│   ├── handout_prelude.typ        # 自包含讲义模板（不依赖 Typst Universe 包）
│   ├── deps.py                    # Typst 自举：查找 / 版本 / 下载 / SHA256 / 缓存
│   ├── typst_assets.json          # 各平台 Typst Release 的固定校验和
│   ├── typst-packages/            # vendor 的 @preview 包（离线编译，逐包带许可）
│   ├── fonts/                     # Notes Serif SC 子集 + OFL.txt + FONT-NOTICE.md
│   ├── study_notes.py             # 讲义 → 填空底稿 → Typst → PDF
│   ├── prelude.typ                # scholia 淡彩 palette（填空笔记用，唯一权威副本）
│   ├── slides.py                  # 投影截图下载 / PDF 合成（可选模块）
│   ├── formatter.py               # 时间戳 / 分钟聚合 / 分块
│   └── cli.py                     # 命令行入口
├── skills/zju-lecture-summarizer/ # 讲义生成 SOP（五段式模板 + 公式规范）
├── skills/zju-lecture-summarizer.manifest.json
├── skills/zju-lecture-summarizer-help/ # 用户命令：登录辅助与故障排查
├── skills/zju-lecture-summarizer-help.manifest.json
├── skills/zju-lecture-summarizer-login/      # 用户命令：打开独立登录窗口 / 清除登录态
├── skills/zju-lecture-summarizer-login.manifest.json
├── skills/scholia-notes/          # 填空式学习笔记 Skill（MIT，独立授权）
│   ├── SKILL.md / LICENSE / README.md / THIRD_PARTY_NOTICES.md
│   ├── references/                # API / 风格指南 / 排错 / 格式规范
│   └── prelude.typ                # 生成副本（同步自 zju_lecture/prelude.typ）
├── skills/scholia-notes.manifest.json
├── SECURITY.md                    # 威胁模型 / Cookie 生命周期 / 已知边界
├── CHANGELOG.md                   # 版本历史
├── docs/                          # 技术文档与历史 issue 记录
├── adapters/                      # 其它宿主的接入示例（不进入插件包）
├── tests/                         # 回归测试（含隐私扫描与插件形态测试）
├── tools/                         # 打包、schema 生成、隐私扫描、冒烟测试
├── icon.png / icon-dark.png
├── LICENSE / ATTRIBUTION.md
└── README.md
```

主链路（两条 PDF 链路共用同一份 Markdown 与同一套公式转换）：

```text
回放 URL / sub_id
  → zju_fetch_transcript（先匿名，按分钟 / 逐句 / 分块 / JSON；鉴权条件见下）
  →（可选）zju_extract_courseware（本地课件校准术语）
  → Agent 写 Markdown
  → zju_write_note：命名 → 修公式 → 校验 → 写文件 → 排版同名 PDF
  →（可选）zju_build_study_notes：讲义 →（draft）填空底稿 →（patch，一次写回挖空）
    →（compile）scholia PDF + 逐页 PNG
```

字幕保留 `classroom.zju.edu.cn`：先匿名请求，**仅 HTTP 401/403** 时调用 `_resolve_cookie`
（进程缓存 → `ZJU_COOKIE` → `ZJU_COOKIE_FILE` → `zju_login` 保存的本机登录态 → Edge）
解析 `_token`，用 Bearer 重试一次。
兼容两种返回：`ainew` 用 `BeginSec` / `Text`，老课程 `ai` 用 `time` / `zhtext` / `entext`
（以第一条时间戳为相对零点换算秒数）。
字幕鉴权属于核心链路，**不需要开启登录辅助工具**（`enableLoginTools` 只控制视频直链与读 Cookie 工具）。
字幕请求**不发 Cookie 头**；官网实证同一课匿名 403、Bearer-only HTTP 200 / code 0、返回 942 条字幕，
不需要更换主机。CLI 默认自动重试，`--no-login` 可关闭，`--cookie-file` 可指定本地文件；没有明文 token 参数。

### 一键登录窗口（`zju_login`）

读 Edge 数据库是次级路径：ABE 打开后，外部进程连 DPAPI 也解不开 v20 Cookie，退出 Edge 也没用。
因此本机没有可用登录态、或登录态被服务端判定失效时，走独立登录窗口：

1. `browser_login.py` 用 `--user-data-dir=<用户状态目录>/login-profile` 启动 Edge / Chrome，
   带 `--remote-debugging-port=0`；端口只绑 `127.0.0.1`，不碰用户日常 Edge。
2. 浏览器打开用户给的课堂链接（仅 `https://*.zju.edu.cn`）；用户在页面里完成 SSO / 2FA。
3. 插件每 1.5s 通过 CDP `Storage.getCookies` 读取 Cookie，只保留课堂主机与
   `.zju.edu.cn` 父域（`_token` 所在），排除其他 ZJU 子域与相似域名。
4. 检测到可解析的 `_token` 后，`save_session()` 只保存 Cookie 头：
   Windows 用 DPAPI（`CryptProtectData`，绑定当前用户），macOS / Linux 用 0600 文件；
   不保存账号密码。
5. 关闭浏览器，`zju_login` 把 Cookie 放进本进程缓存；Agent 重试字幕一次。
6. 服务端仍返回 401/403 时，`_forget_cookie("session")` 删除登录态与专用 profile，
   下次 `zju_login` 从真正的登录页开始，而不是重放死 Cookie。

`clear=true` 删除登录态与独立浏览器 profile；无图形界面、未安装浏览器或策略禁用远程调试时，
返回 `no_browser` / `devtools_blocked`，此时才回退到 `ZJU_COOKIE_FILE` 高级方案。

## 2. 安装形态与依赖

| 形态 | 载体 | 依赖 |
| :--- | :--- | :--- |
| dsh 原生插件 | 仓库根目录的 npm 包（`package.json` + `cordis.patch.yml` + `lib/`） | pnpm 装 peer；Python 3.9+；Typst 由插件自举 |
| 标准 MCP + Skill | `server.mjs` 拉起 stdio MCP Server | PATH 上的 `node`；Python 3.9+ |
| MiniMax Code 插件包 | `tools/build_plugin.py` 产出的 `dist/*.zip` | 同上 |
| 命令行 | `python -m zju_lecture.cli` | Python 3.9+；`pypdf` 仅 PDF 课件需要 |

**Typst 自举**（v2.1.0）：`zju_lecture/deps.py` 把「本机没装 Typst」从静默失败变成一次可解释的准备：

1. 查找顺序 `ZJU_TYPST_BIN` → 插件缓存 `%LOCALAPPDATA%\dsh-zju-lecture\typst\v<版本>`（macOS/Linux
   对应 `~/Library/Caches`、`~/.cache`）→ `PATH` → 常见安装目录；
2. 版本低于 0.13.0 时提示升级（0.13 是 `--package-path` 与现有模板的下限）；
3. 找不到且允许自动安装时，从 GitHub Release 下载对应平台归档，**只信任**
   `zju_lecture/typst_assets.json` 里钉死的 SHA256，解压后再用 `typst --version` 复核；
4. 下载失败会写一个 6 小时的冷却标记，避免每写一份讲义都卡一次超时。

`ZJU_TYPST_AUTO_INSTALL=0` 关闭自动安装；`ZJU_TYPST_MIRROR` 可给下载 URL 加镜像前缀
（只影响传输路径，哈希仍按清单校验）。`zju_doctor` 报告上述状态，`install=true` 立即重试安装；`login=true` 才读取本机登录态检查可用性。

**离线编译**：6 个 `@preview` 包（scholia / frame-it / marginalia / theoretic / showybox / noteworthy）
已 vendor 到 `zju_lecture/typst-packages/`，编译统一带 `--package-path` 与工作区内的
`--package-cache-path`，填空笔记首次编译不再访问 Typst 包注册表。逐包保留 `LICENSE` / `UNLICENSE`
与 `typst.toml`（后者是 `@preview/name:version` 解析的依据），只删除 README 与模板示例。

**peer 依赖**：`lib/index.js` 里的 `@deepseek-ai/*` 全部是 `peerDependencies`
（与 `dshmarket` 一致），由 pnpm 在 `dsh plugin add` 时装进 profile 的 `node_modules`
（当前是 `@deepseek-ai/schemastery` 3.18.x）。直接解压 zip 加载会报：

```text
Cannot find package '@deepseek-ai/schemastery' imported from ...\\lib\\index.js
```

若一定要用本地目录，先补一颗可解析的 schemastery（其余 `@deepseek-ai/dsh-*` 仍由 dsh 运行时提供）：

```bash
cd /absolute/path/to/zju-lecture-agent-plugin
npm install --no-save --no-package-lock @deepseek-ai/schemastery@^3.18.1
dsh plugin --profile desktop add file:/absolute/path/to/zju-lecture-agent-plugin
```

`--no-save --no-package-lock` 让这次安装只落进目录的 `node_modules`，不改 `package.json`。

**版本要求**：dsh 按 `peerDependencies` 中的 `@deepseek-ai/dsh-*` 范围校验运行时版本，
本插件声明 `>=0.2.0-rc.2 <0.3.0-0`，不匹配时需要显式的版本豁免
（`dsh plugin allow-version`）。

**GitHub 安装的 5 秒预检**：dsh 宿主在启动 pnpm 前会执行
`git -c credential.helper= ls-remote -- <repo> HEAD`，默认 5 秒超时
（`plugin-manager` 的 `githubConnectionTimeoutMs`，最小 1000ms）。超时报
`connection to github.com timed out after 5000ms`，此时 pnpm 尚未启动、profile 不会被修改。
dsh 只读 `HTTPS_PROXY` / `HTTP_PROXY` / `ALL_PROXY` / `NO_PROXY`，不读 Windows 系统代理，
git 也不读；浏览器能打开 GitHub 不代表预检能过。处置顺序：优先用 npm 包名安装（不走 GitHub）；
必须走 GitHub 源时给 git 配代理，并让 dsh 进程能读到同一组环境变量；或在 profile 的
`cordis.patch.yml` 里把 `plugin-manager` 的 `githubConnectionTimeoutMs` 调大后重启。

**Python 探测顺序**：插件配置项 → 环境变量 `ZJU_PYTHON` → DeepSeek Harness 自带 Python →
PATH 上的 `python3` / `python` / `py -3`。

**client 元数据在 Host 启动时缓存**：`dsh.client` 新增或修改后，只重装插件、甚至刷新页面都不够，
必须**完全重启 DeepSeek Harness**；可在 `cordis_inspect_query` 的 `Slots` →
`factory:dsh-zju-lecture-note` / `settings.section` 验证。

**浏览器半边的两个席位（同一份配置）**：`lib/client.js` 只创建一个 `PipelineSettings`
控制器、一个 `PipelineSection` 组件，然后从两个席位挂同一个页面：

| 席位 | 位置 | 注册 |
| :--- | :--- | :--- |
| `settings.section` | 设置弹窗的左栏「浙大智云课堂讲义」 | `id: PANEL_ID`、`order: 25` |
| `sidebar.panellist` + `main` | 主界面左栏「智云讲义」一行，点开在主区域显示同一页 | 行 `id` 与面板 `key` 都取 `PANEL_ID` |

- 侧边栏按 id 调 `ctx.layout.selectPanel(id)`，所以**行的 `id` 与 `main` 的 `key` 必须一致**；
  两处都引用同一个 `PANEL_ID = 'zju-lecture'` 常量，不要写死两份字符串。
- 两个席位嵌套注册（`main` 外层、`sidebar.panellist` 内层），任一侧失败都不会留下半套入口。
- `sidebar.panellist` 没有图标字段：注册项自己画 SVG，用 `currentColor` 才能跟随行的
  悬停/选中颜色；`label` 是 thunk，跟随语言切换。
- `main` 占的是整列页面，页首要用 `calc(20px + var(--dsh-frame-top-clearance, 0px))` 留出
  窗口标题栏的高度，否则 Windows 上第一行会被标题栏压住。
- 面板页把标题渲染成 `h1`（`asPage`），设置弹窗里仍是 `h2`（弹窗自己提供标题）。

## 3. 工具与开关分层

v2.0.1 起，「字幕 → 讲义 → PDF」主链路与投影、填空笔记等可选能力解耦；可选工具按开关注册。
字幕鉴权与一键登录是核心链路的一部分：先匿名，401/403 后自动读取本机登录态，仍失败就由 `zju_login`
打开独立登录窗口；登录辅助开关只控制两个可选辅助工具。

| 分层 | 工具 | 依赖 | 默认 |
| :--- | :--- | :--- | :--- |
| **字幕主链路** | `zju_parse_url` / `zju_fetch_transcript` / `zju_extract_courseware` / `zju_check_note` / `zju_write_note`（含自动 PDF） / `zju_login` / `zju_doctor` | 字幕接口（先匿名，401/403 自动用本机登录态）+ 一键登录窗口 + 本地文件 + 可选 Typst | 始终开启 |
| **填空笔记** | `zju_build_study_notes` + `scholia-notes` Skill | 本机 Typst | 关闭（`enableStudyNotes`） |
| **投影抓取** | `zju_fetch_slides` | 登录态 + 截图下载 + PDF 合成 | 关闭（`enableSlides`） |
| **投影插图** | （`zju_fetch_slides` 的子开关） | 依赖投影抓取 | 关闭（`embedSlideImages`） |
| **登录辅助** | `zju_get_video_url` / `zju_read_browser_cookie`；不影响字幕鉴权与 `zju_login` | 内存缓存 / `ZJU_COOKIE` / `ZJU_COOKIE_FILE` / 本机 Edge | 关闭（`enableLoginTools`） |

- dsh 默认注册 **7** 个工具；`enableStudyNotes` +1、`enableSlides` +1、`enableLoginTools` +2，
  全开 **11** 个。
- **`.volatile()` 字段是引用，不是布尔值**：dsh 把它们投影成 `{ get() }`，供插件在设置改动后
  读取新值。`lib/index.js` 的 `readSetting()` 统一解包；直接写 `config.enableSlides === true`
  会永远得到 `false`——2.1.1 修的「设置全开仍只有字幕」就是这个原因。新增设置项时务必走
  `readSetting()`，并补一条 ref 形状的测试。
- MCP 未设置新变量时保持旧行为（11 个）；仓库自带的 `zju-lecture.mcp.json` 默认关掉三个可选模块（7 个）。
- 关闭时：不注册对应工具、不加载对应模块、Skill 不追加对应附录；系统提示会说明
  「这个模块已关闭」，Agent 不会调用或假装调用。
- 实现上，`lib/index.js` 用 `registerableTools()` 过滤；`mcp_server.available_tools()`
  同步过滤 `tools/list`；直接调用会抛 `SlidesDisabledError`（RPC 侧是 `isError`）。
- `zju_lecture/__init__.py` 用 PEP 562 懒导出 `download_slides` / `build_slides_pdf` / `SlideError`；
  `mcp_server.py` 只在进入 `zju_fetch_slides` 分支时才导入 `zju_lecture.slides`
  （纯字幕进程的 `sys.modules` 里不会出现截图模块，有子进程测试守住）。
- dsh 单独把 `zju_fetch_slides` / `zju_login` 的超时提高到 600s（下载截图 / 等待用户登录），
  其他工具仍用配置值。
- 投影抓取与填空笔记互不依赖；登录辅助也与投影抓取解耦——投影工具会自己解析登录态。
- 投影截图默认下载到 `<工作区>/ppt-assets/<sub_id>/`（已 gitignore），Agent 挑 **3–8 张**
  关键页引用进讲义；接口没有文字层 / OCR，需要幻灯片原文时走 `zju_extract_courseware`。
- 登录辅助默认关闭（dsh `enableLoginTools=false`），只影响视频直链与读 Cookie 工具，不影响字幕。
  `zju_login` 是核心工具，始终注册；字幕鉴权由字幕工具内部自动完成，不需模型先调读 Cookie 工具，
  也不新增工具或凭据参数。
- 三个用户命令：
  - `zju-lecture-summarizer-help` 做 401/403、代理与依赖排查；
  - `zju-lecture-summarizer-login` 只做「打开登录窗口 / 清除登录态」；
  - `scholia-notes` 只在 `enableStudyNotes` 打开时进入模型技能目录。
  两个命令 Skill 都是 `userInvocable: true` / `modelInvocable: false`，不干扰正常的讲义生成。

### 环境变量

| 变量 | 作用 |
| :--- | :--- |
| `ZJU_PYTHON` | 指定 Python 解释器 |
| `ZJU_WORKSPACE` | 相对路径的解析根；dsh 插件自动传入 session workspace |
| `ZJU_BACKUP_DIR` | `zju_check_note` / `zju_write_note` 的备份目录（默认系统临时目录） |
| `ZJU_COOKIE` / `ZJU_COOKIE_FILE` | 显式本机登录态（优先级最高）；存在且损坏时会挡住 `zju_login`，字幕仅在 HTTP 401/403 后自动使用 |
| `ZJU_LOGIN_DIR` | `zju_login` 保存登录态与独立浏览器 profile 的目录（默认用户状态目录） |
| `ZJU_BROWSER_BIN` | 指定登录窗口使用的浏览器可执行文件（默认 Edge → Chrome → Chromium） |
| `ZJU_RENDER_PDF` | 默认 `0`（MCP）；对应 dsh `renderPdf`（默认开） |
| `ZJU_TYPST_AUTO_INSTALL` | 缺 Typst 时自动下载安装（默认 `1`；dsh 对应 `typstAutoInstall`） |
| `ZJU_TYPST_BIN` | 指定已有 Typst 可执行文件（优先级最高） |
| `ZJU_TYPST_MIRROR` | Typst 下载 URL 的镜像前缀，例如 `https://ghfast.top/` |
| `ZJU_TYPST_CACHE` | 覆盖 Typst 缓存目录（默认用户缓存；测试与换盘时用） |
| `ZJU_ENABLE_STUDY_NOTES` / `ZJU_ENABLE_SLIDES` / `ZJU_EMBED_SLIDES` / `ZJU_ENABLE_LOGIN_TOOLS` | 可选模块开关；最后一项只控制登录辅助工具，字幕鉴权不受影响 |
| `ZJU_ALLOW_SENSITIVE_PATHS` | 显式关闭本地敏感路径保护（不推荐） |

相对路径解析顺序：绝对路径 → `ZJU_WORKSPACE` → `PWD` → 服务进程 cwd；都找不到时，
错误信息会列出**尝试过的绝对路径**。

## 4. 主链路：`zju_write_note` 内部

一次工具调用完成五件事，Agent 不需要再调第二个工具：

1. **命名**：`name` 参数优先（Agent 按「上课日期 + 本节内容」起名）；缺省回退
   `知识总结-<sub_id>-<课程简称>.md`。同名默认拒绝覆盖，返回 `exists`，要覆盖须显式 `overwrite=true`。
2. **修公式**：`fix=true`（默认）先跑一遍可机械修复的规则（见 §7）。
3. **校验**：静态扫描讲义，按 `code` 聚合报告。
4. **写文件**：原子替换；回写前备份到 `ZJU_BACKUP_DIR`。
5. **排版 PDF**：把同一份内容写进 `<工作区>/.zju-lecture/handout/<stem>/main.typ` 并编译；
   成功时 PDF 落在讲义同目录，返回一行 `PDF: <路径>（N 页）`；失败只回一行
   `PDF 跳过: …`，Markdown 已写入。

省 token 的约定：`zju_write_note` 已经包含校验，**通常不需要**再调 `zju_check_note`；
只有手工改过文件、或想给已有讲义补 PDF 时才用 `zju_check_note(pdf=true)`。
同一节课的字幕也只抓一次（长课用 `chunked` 视图分批总结）。

## 5. 阅读版讲义 PDF

实现：`zju_lecture/handout.py` + `zju_lecture/handout_prelude.typ`。

- **自包含**：`handout_prelude.typ` **不 import `@preview/scholia`**，不访问 Typst 包注册表；
  样式全部内联进生成的 `main.typ`，离线也能编译。`@preview/scholia` 只继续用于可选的填空笔记。
- **工程位置**：`<工作区>/.zju-lecture/handout/<stem>/`（已 gitignore），PDF 与讲义同目录。
  不导出逐页 PNG——只有填空笔记需要。
- **版式**：封面（标题 / 副题 / 日期）、目录（≥3 节时）、标题层级、正文、列表、三线表、
  公式、代码、引用、工作区图片。
  - 版心、封面、边注栏、字号等**数值**统一见
    [`typography-spec.md`](../skills/scholia-notes/references/typography-spec.md)；
    本节只保留机制。
  - 一级标题：灰蓝编号 + 蓝色标题 + 细线；方框淡彩底 + 左侧竖线、无圆角；
    证明以斜体 `Proof.` + **块末** qed（方块落在证明最后一行，不是第一行）。
  - 各级标题后的间距自 2.2.2 起加大（用户在实地会话里要求「小节标题后的行间距
    适当大一些」）；2.2.4 又把**上方**留白拉开（节标题 12pt → 22pt、章标题 20pt → 24pt），
    否则绿色小节标题紧贴上一段、看不出新节从哪里开始。具体值见规范 §2；两条链路同步改。
  - `par.first-line-indent` **不可靠**：它只在「前一个兄弟元素是段落」时生效，
    标题 / 块 / 图 / 公式后的段落一律不缩进 ⇒ 正文改用行内 `#h(2em)` 顶首行；
    直觉块不缩进（块自身的左内边距已经分开）。
  - 块级公式的上下间距吃 `par.spacing`，压段间距会把公式压到下一段上 ⇒ 用
    `#show math.equation.where(block: true): set block(above: …, below: …)` 解耦
    （数值见规范）。
  - 行内公式的墨迹会溢出「行盒」：Typst 的行内数学盒子高度是**固定值**（11pt 下
    ≈0.68em，`measure($frac(1,2)$)` 与 `measure($x$)` 都是 7.51pt），分式的分子/分母、
    大算子的上下限压到邻行上。解决办法是两处**显式**留白：模板里的
    `#show math.equation.where(block: false): it => box(inset: (top: …, bottom: …), it)`
    给每个行内公式补一点；`study_notes.pad_inline_math()` 再给分式/根式/矩阵/大算子
    这类「结构上会撑高」的公式包一层 `#box(inset: (bottom: …))`。只按最大值统一给会把
    只有 `$x$` 的行也撑松，所以按结构分级（数值与实测见规范 §3.2）。
  - 边注用 `box(width: 0pt, context { let p = here().position(); place(top + left, dx: page.width - p.x - note-width - right-pad, …) })`：
    `note-width` / `right-pad` 的数值见规范；直接 `context` + `place(top + right)`
    会把边注甩到页面顶端。
- **标记语法**（转义前处理；`____` 先于转义，否则会被变成 `#fillin` 后漏掉）：

  | 标记 | 装置 |
  | :--- | :--- |
  | `[直觉]` | `#note`（青绿淡底） |
  | `[定义] 标题 —— 正文` / `[定理]` / `[命题]` / `[例]` | 带标签的方框（**跨段**） |
  | `[证明]` | 斜体 `Proof.` + **块末** qed（**跨段**） |
  | `[练习]` | `#yourturn` + 3 行 `#workspace(n: 3)`（练习块里的短 `____` 一律丢弃） |
  | `[边注]` / `[边注!]` | 右侧留白边注（`[边注!]` 带强调） |
  | `[强调]` / `[易错]` / `[弱注]` / `[分隔]` | 行内高亮 / 提示 / 弱化 / 分隔线 |
  | `---`（独占一行） | 同 `[分隔]` 的细分隔线（不再被智能标点排成孤立「–」） |
  | `____` | `#fillin(width: 2.2cm)`（灰色，提示留给读者写） |
  | `[缺口: …]` | `#gap` 留白 |
  | `<label>` / `@label` | 两遍扫描后生成原生交叉引用 |

  **标记块的边界**：框类装置与 `[证明]` 是「块」而不是「一行」——从标记行一直收到
  下一个标记行 / 标题 / 整行粗体的伪标题（`**周期函数的处理** \`[00:22]\``）。
  块内的空行是段落分隔，`$$…$$`、列表、表格都留在装置里；`_render_block_sequence()`
  负责把它们排成装置内容（块内段落不加 `#h(2em)`）。单段装置（`[直觉]` / `[练习]` /
  `[边注]` / `[强调]` …）仍只吃标记行那一句。
  这条规则同时修掉两个实地问题：定理陈述里的块级公式被甩到框外；`[证明]` 遇到空行就
  收尾，qed 方块停在一两行之后，读起来像「证明到这就结束了」。两条链路（
  `handout.py` 与 `study_notes.py`）用同一套口径；块内段落仍计入「方框:正文」的分母，
  避免比例检查误报。

  块内正文在「题目 / 切入点 / 关键步骤 / 易错点」四个标签紧跟句末标点
  （`。！？；`）时自动断段（`study_notes.split_review_labels()`）：模型常把复习版例题的
  四段写进同一行，不断段的话框里就是一大坨（实地讲义实测）。

  **自测题**（`**1.** 题干` + `<details><summary>答案</summary>…</details>`）在两条链路里
  分别排成 `#selftest`（琥珀框，标签「自测题 n」，手写的 `**1.**` 编号交给标签）与
  `#answer`（框外，淡灰左线 + 「答案」标签）。题干是紧挨 `<details>` 的那一段；
  `<summary>` 的文字当标签。这样题目与答案之间有一道清楚的边界，也不会再把
  `<details>` 印成字面量（填空链路以前会）。两个装置分别定义在 `handout_prelude.typ`
  与 `zju_lecture/prelude.typ`。

  标题手写的编号（`1.` / `1.2` / `一、` / `（三）`）**一律剥掉**，编号只由 Typst 生成。
- **数学**：与填空笔记共用 `study_notes.latex_to_typst`：`pmatrix` / `bmatrix` / `cases` / `aligned`
  机械转成 `mat` / `cases` / 对齐换行；多字母标识符（`AC`、`e^{-st}`、`BVP`）按规则转成
  直立或拆乘积，避免 Typst 报 unknown variable。
- **方框预算**：编译报告里给正文段落数、方框数、方框:正文比值（1:8 以内稳，超过 1:4 告警）、
  逐节方框数。规范要求每节方框合计 ≤ 2，框的唯一正当理由是「后面会被回指」。

### 配色

浅色 `soft-palette` 的**唯一权威来源**是 `zju_lecture/prelude.typ`；完整色表、
对比度与「极差 1.11 是刻度跨度」的口径见
[`typography-spec.md`](../skills/scholia-notes/references/typography-spec.md) §7。
这里只保留机制：

- `handout_prelude.typ` 的 `#let palette` 与 `handout._PALETTE` 是**生成副本**：
  改色只改 `prelude.typ`，再跑 `python tools/sync_palette.py`，
  `--check` 校验三处逐角色一致（`tests/test_palette_sync.py` 也会跑）。
- 页面 `fill: palette.bg`；`handout._tint` 混向 `bg` 而不是纯白，才与 Typst `tint()` 同算法。
- 深色主题（slate）由上游 scholia 自带，本项目不注入 `use-palette`。

### 字体与可再分发性

完整的角色、回退链与许可列见
[`typography-spec.md`](../skills/scholia-notes/references/typography-spec.md) §1。
这里只保留机制：

- 两条链路默认都只用可再分发字体：STIX Two / Libertinus / 随包 `Notes Kai SC` 与
  `Notes Serif SC` / Noto / Source Han / DejaVu；商业字体不在生效栈里。
- `Notes Kai SC` 是 LXGW WenKai 的 GB2312 子集（OFL，上游有 Reserved Font Name，
  因此**改名**）；`Notes Serif SC` 是 Noto Serif SC 的子集（OFL）。两者都随附
  `OFL*.txt` 与 `FONT-NOTICE.md`。
- 填空笔记的 vendored `scholia` 已 patch `src/fonts.typ` 的 `default-fonts`，
  所以 `note` / `sidenote` / `label-it` 也跟随同一套字体；补丁由
  `tools/vendor_typst_packages.py` 重放，记录在 `VENDORED.md`。
- 对外分发 PDF 前用 `pdffonts out.pdf` 核对一次：若出现 `Optima` / `Avenir Next` /
  `Menlo` / `Songti SC` / `SimSun` / `Microsoft YaHei`，说明命中了系统商业字体，
  换一份完整 OFL 字体再排。

## 6. 填空笔记链路

`zju_lecture/study_notes.py` 负责两段：

- `mode=draft`：讲义 → 填空底稿（标题层级映射、正文原样搬运）。
  骨架**不再逐节插 `[直觉]` / `[练习]` / `[边注]` 空占位**：文件头只有一条 HTML 注释
  说明这些装置可选，加不加、加在哪儿由内容判断。**公式、表格、列表、行内代码都原样保留成 Markdown**：
  底稿是给人/模型改的，转换只在 `mode=compile` 做一次。
- `mode=patch`：按 `edits=[{old, new}, …]` 一次写回底稿，逐条报告命中/未命中。
  挖空是十几处精确替换，逐条调用编辑工具就是十几次往返（实地会话 35 步里有 12 步
  花在这上面）；这里是同一批修改的一次提交。`old` 默认必须唯一命中，重复时加
  `"all": true` 或加长上下文。
- `mode=compile`：底稿 → `main.typ` + `prelude.typ` → `out.pdf` + 逐页 `page-N.png`，
  并报告编译错误、方框预算与悬空回指。

接口细节：

- 骨架**不会**替使用者插 `[定义]/[定理]/[证明]`——那三个框该不该用是内容判断。
- 底稿可以写 `<!-- … -->` 注释，转成 Typst 块注释，不渲染、也不计进正文段落。
- 数学转换是**幂等**的：`_plain_word` 认识转换器自己会产出的名字（`frac` / `cal` / `sum` /
  `quad` / `wide` / `slash` / `"Res"` …），所以 `latex_to_typst(latex_to_typst(x)) == latex_to_typst(x)`，
  不会被拆成 `s u m` / `f r a c`。引号串（`"Res"`）原样搬运，不再被二次加工。
- 间距命令走 Typst 的真实间距：`\quad` → `quad`（1em）、`\qquad` → `wide`（2em）、
  `\,` → `thin`、`\;` → `med`。早先映射成空格，而 Typst 会折叠连续空格，
  于是「并排的两条公式」粘成 `0∇×H`（实地会话里 Agent 只能写脚本拆公式块）。
- 行内数学（`inline=True`）把 `/` 排成平排的 `slash`，块级公式仍排上下分式：
  `$1/r$` 不再把行距顶高，不必手改成 `r^{-1}`。
- Markdown 的 `>` 引用块 → `#quoted[…]`（左侧细线 + 灰色小字）。Typst **没有** `>`
  引用语法，旧实现把 `>` 原样印进 PDF；多条 `> **字段**：…` 按行换行，不再粘成一句。
- 方框预算按**最小**小节统计：`## 二、分章详解` 下挂 7 个 `### 2.x` 时逐 `2.x` 计数，
  不会把整章的框算到同一节。
- GFM 表格 / `- ` 与 `1.` 列表 / 行内反引号在 `render_typst` 里有对应分支：表格 → `#table(…)`、
  列表 → Typst 列表、反引号 → raw（内容不转义）。以前表格只在 `build_draft` 转、`render_typst`
  不认，底稿里的 `#table(…)` 会被当正文转义成 `\[a\]`。
- Typst markup 里 `_` / `\` / `[` / `#` / `@` 都要转义；转义顺序**先 `\` 再 `_`**，
  否则 `_` 刚加的反斜杠会被二次转义。
- `dz` / `dx` 按微分约定拆成 `d z` / `d x`；`diag` 这类单词不拆。
- `zju_lecture/prelude.typ` 是唯一权威副本；`skills/scholia-notes/references/prelude.typ` 是生成副本，
  `tools/sync_skill_assets.py` 同步、`tests/test_study_notes.py` 校验逐字节一致。

## 7. 格式规范与公式检查

`zju_lecture/note_lint.py` 是两道闸门里的第二道：

1. **规范写进 Skill**：行内 `$...$` / 独立 `$$...$$`、`\frac{分子}{分母}`（两侧都带花括号）、
   绝对值 `\lvert ... \rvert`（不写裸 `|`）、虚数单位 `\mathrm{i}`、中文不塞进 `\text{}`、
   `<details>` 写成多行。
2. **产出后自检**：`zju_check_note` 静态扫描，捕获「表格列被裸竖线截断」「行内公式没闭合」
   「块级公式没独立成行」「`\frac` 缺花括号」「单行 `<details>`」这类会让整篇散架的问题。

```bash
python tools/check_note.py 讲义.md            # 只检查
python tools/check_note.py --fix 讲义.md       # 自动修正机械问题
```

自动修复只做**语义无歧义**的改写，且只作用于围栏代码块与行内代码之外
（讲义里「这样写是错的」示例不会被改坏）；回写前备份到 `ZJU_BACKUP_DIR`，再原子替换。
需要判断的（未闭合的 `$`、`\text{}` 里的中文、裸虚数单位）保持原样并继续报出来。

报告**按问题类型聚合**：59 处同类错误只打印一次 `[错误] display_not_isolated × 59`，
附有界行号列表与少量示例（`max_samples` 可调）。

规范本体（语义对应、预算、禁止事项、LaTeX → Typst 对照）在
[`skills/scholia-notes/references/format-spec.md`](../skills/scholia-notes/references/format-spec.md)，
两条 PDF 链路共用；`references/mapping.md` 是速查表。

## 8. 隐私设计

### Cookie 从哪里来、到哪里去

1. 来源只有本地：内存缓存 → `ZJU_COOKIE` → `ZJU_COOKIE_FILE` → `zju_login` 保存的登录态 → 本机 Edge；
2. 校验：拒绝换行（HTTP 头注入）、空 name、超长；不合法只返回原因，不回显内容；
3. 使用：字幕先匿名，仅 HTTP 401/403 后自动读取本地登录态、解析 Bearer 重试一次；
   字幕不发 Cookie 头，Bearer 仅发往 `classroom.zju.edu.cn`，跨域重定向拒绝；投影等沿用原边界（见下）；
4. 缓存：Python 子进程内存；
5. 回显：没有；工具 schema 中没有 cookie / password / reveal / domain 参数；
6. 日志：所有 stdout / stderr 经过 `SecretRedactor`；
7. 临时文件：只读打开优先；必须复制时连同 `-wal` / `-shm` 一起复制（刚登录的行可能还在 WAL 里），
   权限 0600，读完覆写并删除；
8. 落盘：只有 `zju_login` 保存的登录态与独立浏览器 profile。登录态仅含 Cookie（不保存账号密码），
   Windows 为 DPAPI 密文，macOS / Linux 为 0600 文件；`zju_login(clear=true)` 二者一起删除。
   CDP 只连接 `127.0.0.1` 随机端口，端口与浏览器生命周期由工具管理。

Cookie 不是工具参数：`zju_fetch_transcript` / `zju_fetch_slides` / `zju_get_video_url` 不接受 cookie 参数，
`zju_read_browser_cookie` 也没有参数；登录态只能由 `zju_login`、本地配置或本机 Edge 提供。
字幕匿名成功时不读缓存、环境变量、文件或 Edge 凭据；401/403 后读不到凭据 / 遇到 ABE 时，
调用 `zju_login` 打开独立登录窗口，不向模型索要 Cookie，也不保证关闭 Edge 能解决。
`ZJU_COOKIE` / `ZJU_COOKIE_FILE` 存在时优先级最高，配置损坏会挡住 `zju_login`——诊断文本会明确要求先修/移除。

### 本地文件

`zju_extract_courseware` 和 `zju_check_note` 只接受指定扩展名，并拒绝敏感文件名/目录
（`.env*`、`*credential*`、`*.pem`、`Cookies`、`Login Data`、`.ssh`、`.dsh` 等）。
凭据类单词按分隔符**整词匹配**（`my-secret.txt` 拒绝、`secret sharing 第5章.md` 放行），
`config.json` 这类通用名不再被拒。符号链接会先解析真实路径再判定。
确有必要时可用 `ZJU_ALLOW_SENSITIVE_PATHS=1` 显式关闭保护。

### 网络

- TLS 证书校验**永远不会被关闭**。信任库按 `certifi` → 随包 `cacert.pem` → 系统根证书三级回落；
  三级都不够时才失败，并返回原因 + 下一步（当前信任库、CA 张数、`HTTPS_PROXY`、该装什么）。
- 瞬时故障（`IncompleteRead` / `SSLEOFError` / 超时 / 5xx）重试 3 次，指数退避 + 抖动；
  证书校验失败**不重试**。字幕 HTTP 401/403 只做一次 Bearer 重试，不能循环尝试；
  区分 HTTP 状态、接口业务错误与本地凭据读取失败，不把 403 直接判为校园网限制或要求更换后端。
- 课堂 API 的 Cookie（投影 / 视频直链）与 Bearer 仅发往 `classroom.zju.edu.cn`；字幕不发 Cookie 头。
  跨域 302 直接拒绝，避免 `urllib` 把 `Cookie` / `Authorization` 头重发到第三方域。
- 投影截图只允许 `https://*.zju.edu.cn`；ZJU 的 `http://` 自动升级 HTTPS；
  Cookie 只给 ZJU 图片主机、不发 Bearer；跨主机重定向剥离凭据；写盘限制在工作区。

### 数据会离开本机的部分

字幕与课件文本会作为工具结果进入宿主模型上下文，由你选择的模型提供方处理——这是使用大模型
整理讲义的固有代价。插件本身不收集、不额外上传、不写遥测；除 `zju_login` 保存的本机登录态与
独立浏览器 profile（可用 `clear=true` 删除）外，不写用户目录。

### 可机器验证

```bash
python tools/privacy_scan.py              # 工作区
python tools/privacy_scan.py --history    # 连同 git 历史
python tools/privacy_scan.py --tarball dist/*.tgz   # npm 发布产物
```

## 9. 开发与测试

```bash
python -m unittest discover -s tests -v     # 全部回归测试（含插件形态与隐私测试）
python tools/build_plugin.py --validate     # 按插件规范校验 MCode 包结构
python tools/check_note.py 讲义.md           # 讲义渲染规范检查
python tools/privacy_scan.py                # 工作区隐私扫描
python tools/privacy_scan.py --history      # 连同 git 历史一起扫
python tools/export_schemas.py              # 改动 TOOLS 后重新生成适配器 schema
python tools/export_dsh_tools.py            # 改动 TOOLS 后重新生成 dsh 工具定义
python tools/build_skill_manifest.py        # 改动 Skill 后重新生成 sha256 清单
python tools/sync_skill_assets.py           # 改了 zju_lecture/prelude.typ 后同步到 Skill 目录
python tools/sync_skill_assets.py --check   # 只校验一致性（发布闸门用）
python tools/sync_palette.py                # 改了 soft-palette 后同步讲义模板与 handout._PALETTE
python tools/sync_palette.py --check        # 只校验配色三处一致
node tests/bridge_smoke.mjs                 # 端到端：拉起 Python 核心并调用一次工具
node tests/bridge_error_smoke.mjs           # 端到端：确认 MCP 的 isError 会冒泡成异常
node tests/bridge_workspace_smoke.mjs       # 端到端：相对路径按 session workspace 解析
node tests/plugin_apply_smoke.mjs           # 插件形态：默认 7 工具 / 打开后 11 工具
node tests/client_settings_smoke.mjs        # 设置页行注册与写字段
python tools/refresh_ca_bundle.py --check   # 检查随包 CA 是否完整（≥50 张根证书）
python tools/smoke_test.py --sub-id <sub_id>  # 对已安装包跑端到端冒烟（--dir 可指定包目录）
```

测试覆盖：URL 解析、时间戳格式化、分块时间区间、课件提取、工具 schema 健全性、
MCP 协议往返（`initialize` / `tools/list` / `tools/call` / 通知不响应）、
FIPS-197 AES-128 已知向量、Edge Cookie 失败原因分类、Cookie 主机精确匹配、
Cookie 不回显与错误 redaction、敏感本地文件拒绝、TLS 不降级与三级信任库回落、
瞬时故障重试与证书失败不重试、`isError` 冒泡、跨域重定向拒绝、
讲义公式规范检查与自动修复、隐私扫描器自测、review 批次回归
（行内代码不被改写、修复前备份、DOCX 段落保留、`chunked`/`json` 截断、切片时长、
Cookie WAL 回放、ABE 探测、PDF 报错带解释器路径、bridge 超时语义、系统提示适用范围）、
登录态安全存储 / Cookie 域过滤 / 登录 URL 白名单 / 失效清除 / `zju_login(clear=true)`、
阅读版 PDF 的标记装置与真实编译、配色三处一致与字体可再分发性、填空笔记链路。

> 测试中的 `subprocess` / 管道 / 临时文件在受限沙箱里可能被拒绝；这是环境限制，不是插件缺陷。

## 10. 发布流程

### npm / dsh 插件包

仓库根目录就是 npm 包（包名 `dsh-zju-lecture-note`，当前版本见 `package.json`），发布即发布这个仓库：

```bash
npm login                                   # 首次发布前登录（交互式，需本人操作）
python -m unittest discover -s tests        # 全量测试（prepublishOnly 会再跑一遍）
npm pack --dry-run                          # 先看一眼会打进包里的文件清单
npm pack                                    # 生成 dsh-zju-lecture-note-<version>.tgz
python tools/privacy_scan.py --tarball dsh-zju-lecture-note-<version>.tgz
npm publish --dry-run                       # 预演：不登录也能跑
npm publish                                 # 正式发布；开了 2FA 加 --otp=<6 位码>
npm view dsh-zju-lecture-note version       # 验证
```

- `package.json` 的 `prepublishOnly` 已挂「全量测试 + 隐私扫描」，测试红了发不出去。
- registry 必须是 `https://registry.npmjs.org/`：国内镜像只读，`npm publish` 会 403。
- 版本号不能覆盖：每次发布前必须 bump（八处对齐，见下节）。
- 发布后用户安装：`dsh plugin --profile desktop add dsh-zju-lecture-note`。

`files` 字段是逐文件枚举的运行时清单（`lib/`、`mcp_server.py`、`zju_lecture/*.py`、`skills/`、
`SECURITY.md`、`CHANGELOG.md`、`docs/technical.md`……），**不要**改成整目录——
否则 `__pycache__/*.pyc` 会混进包里（`files` 的优先级高于 `.npmignore`）。

dsh 按 `peerDependencies` 校验运行时版本。若升级 dsh 后插件被跳过，请检查
`@deepseek-ai/dsh-*` 的 peer 范围，或按 dsh 提示使用 `dsh plugin allow-version` 做精确版本豁免。

### MCode 插件包

`python tools/build_plugin.py --install --zip`；运行时文件清单在 `PACKAGE_FILES` / `PACKAGE_DIRS`，
新增文档文件时记得同步，否则装好的包里会出现断链。

### 版本号

版本在**八处**对齐：`package.json`、`pyproject.toml`、`mcp_server.SERVER_VERSION`、
`.minimax-plugin/plugin.json`、四个 Skill manifest（由 `tools/build_skill_manifest.py` 生成）。
`tests/test_dsh_plugin.py` 会断言。

### 插件市场条目

收录条目在 `market-submission/`（`awesome-dsh-plugin` 列表）。改条目后本地校验：

```bash
python - <<'PY'
import yaml
p = 'market-submission/chenqianyu486-sys__dsh-zju-lecture-note.yml'
d = yaml.safe_load(open(p, encoding='utf-8'))
for lang in ('en', 'zh'):
    s = d['description'][lang]
    assert s.rstrip().endswith(('。', '.')), lang
    assert 'scholia' in s and 'typst.app/universe/package/scholia' in s, lang
    print(lang, len(s), 'ok')
PY
```

合并前市场 `plugins.json` 不含本插件是预期行为；站点在合并后自动重建。

## 11. 已知限制

- **Typst 由插件自举（≥ 0.13.0）**：首次排版会按需下载约 20 MB 的官方 Release 到用户缓存目录，
  按仓库内固定的 SHA256 校验；可用 `ZJU_TYPST_AUTO_INSTALL=0` 关闭，改用 `zju_doctor` 的提示手动安装。
  下载失败有 6 小时冷却，不会每次写讲义都重试。
- **阅读版 PDF 的失败是软失败**：Markdown 照常写入，只返回 `PDF 跳过`；`zju_doctor` 能说明缺什么。
- **字体覆盖的边界**：填空笔记的 `fonts:` 参数改不到 `note` / `sidenote` / `label-it`
  （上游包内直接读 `default-fonts`）；随包字体通过 `cjk` 角色进入正文，已能覆盖绝大多数中文。
- **网络依赖**：字幕抓取需要网络，部分课程还需要本机登录态；讲义写入、填空笔记编译
  （已 vendor 包与字体）可在本地完成，但首次安装 Typst 仍需要网络。
- **投影截图没有文字层 / OCR**：接口只返回图片。需要幻灯片原文时让用户提供 `.pptx` 走
  `zju_extract_courseware`；模型不能看图时 Agent 只列截图索引，不臆造内容。
- **Edge 登录态不再是唯一来源**：Chromium 对 Cookie 数据库加独占锁；Edge 127+ 若启用应用绑定加密（ABE），
  v20 Cookie 连 DPAPI 也解不开。插件会读 `Local State` 判定 ABE，但不再把它当死路——
  推荐动作改为 `zju_login`（独立 profile + 浏览器进程内取 Cookie，与 ABE 无关）。
  读库兜底仍会带上 `-wal` / `-shm` 并让 SQLite 回放 WAL。
- **`zju_login` 的边界**：需要图形界面与允许本机远程调试的浏览器；企业策略 / 安全软件拦截时返回
  `devtools_blocked`，无图形界面的服务器返回 `no_browser` 或启动失败，此时才用 `ZJU_COOKIE_FILE`。
  它不会读日常 Edge profile，也不会接收账号密码。
- **PDF 课件**需要可选依赖 `pypdf`（`pip install pypdf`）；其余格式零依赖。
- **SSL / 代理**：信任库三级回落，真正会失败的是**代理做了 HTTPS 解密**或**系统时间偏差过大**；
  错误消息会给出当前信任库、CA 张数、代理环境变量与具体修法。插件不会关闭证书校验。
- **同名 Skill 的磁盘副本会抢名字**：若 `$DSH_HOME/skills/zju-lecture-summarizer/` 下还留着旧副本，
  一个名字只保留一份、重复的仅打 warning，Agent 可能一直读那份过期 SOP。清单里的
  `contentHash`（`sha256:...`）是权威值；插件启动时会在 stderr 打印插件内置版与磁盘副本的 sha256，
  并给出删除路径。
- **git 历史**：历史中已有的个人路径/密钥不会因为当前文件干净而消失；
  用 `python tools/privacy_scan.py --history` 检查，必要时重写历史并轮换凭证。
- **形态别选错**：`tools/build_plugin.py` 产出的是 **MCode 插件包**；装进 dsh 用的是本仓库根目录的
  npm 包（`dsh plugin ... add`）。两者是两套安装方式，不要混。
- **字幕可能需登录，请遵守平台条款**：只抓本人有权访问的回放，一次一节课，不要批量抓取。

## 12. 上游与归属

本插件的来源、参考实现与「未拷贝代码」的边界见
[ATTRIBUTION.md](../ATTRIBUTION.md)（逐文件来源）与
[skills/scholia-notes/THIRD_PARTY_NOTICES.md](../skills/scholia-notes/THIRD_PARTY_NOTICES.md)
（Typst 包、字体、配色归属）。

其中与 PDF 模板直接相关的：

- `@preview/scholia` 0.1.0（MIT，© Eric Yang）是**基于 Typst scholia 模板排版的
  填空式学习笔记**的排版引擎；配色与段落规范由本项目定义，见 scholia-notes 规范
  （`skills/scholia-notes/references/typography-spec.md`）。
  **已随本仓库分发（vendored）**在 `zju_lecture/typst-packages/`，逐包保留上游许可与 `typst.toml`；
- 其余传递依赖（frame-it / marginalia / theoretic / showybox / noteworthy）同样随包分发，
  版本与许可见 `zju_lecture/typst-packages/VENDORED.md`；
- 阅读版讲义模板 `handout_prelude.typ` 是本项目自研、自包含的重写，视觉上参考 scholia 的
  浅色 notes 主题（配色角色、装置语义），**未拷贝上游源码**；
- 上游 scholia 声明自己是受 `loom-notes` 设计启发的独立重写（未复用源码），本仓库亦未分发它；
- 本插件与 Eric Yang 无隶属关系，也未获其背书；「scholia」一词仅作指示性使用。

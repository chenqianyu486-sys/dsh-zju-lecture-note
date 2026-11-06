# 浙大智云课堂讲义插件（ZJU Lecture Agent Plugin）

由 [`nzw806/zju-lecture-summerizer-`](https://github.com/nzw806/zju-lecture-summerizer-) 改编的 DeepSeek Harness 原生插件，提供开箱即用的体验。
面向 **DeepSeek Harness（dsh）** 与任意 **MCP 宿主**（Claude Code / Cursor / Cline / MiniMax Code…）。

> 把浙大智云课堂（`classroom.zju.edu.cn`）的课程回放，变成一份**能直接复习的讲义**：  
> - 结构化 Markdown + 同名 PDF（封面、目录、公式、三线表、边注），在**本机**排好。  
> - 字幕先匿名；401/403 时自动使用本机登录态重试一次。Cookie 只在本机进程内存里使用，工具不收、不回显、不落盘。
> - 核心只用 Python 标准库；PDF 排版用的 Typst、中文字体与 Typst 包由插件自带或首次使用时自动准备（PDF 课件另需可选的 `pypdf`）。  
> - **非官方工具**：与浙江大学及其「智云课堂」平台无隶属关系，也未获其背书。

## 开始使用

- 安装 DeepSeek Harness
- 进入插件→添加插件，复制 npm 包名 dsh-zju-lecture-note 或仓库链接 https://github.com/chenqianyu486-sys/dsh-zju-lecture-note
- 安装并启用插件
- 首次使用：在 **Microsoft Edge**（Windows / macOS）登录智云课堂，或配置 `ZJU_COOKIE_FILE`（一行 Cookie 头）。字幕先匿名，401/403 时自动用本机登录态重试一次，不需要开启「登录辅助」。
- 在新会话中键入 /zju-lecture-summarizer 即可使用插件总结课堂内容，例：  
```text
/zju-lecture-summarizer 帮我总结课程内容 https://classroom.zju.edu.cn/livingroom?course_id=87517&sub_id=1988617&tenant_code=112
```

## 功能特色

- **一句话出讲义**：给回放链接或 `sub_id`，Agent 抓字幕、写 Markdown、修公式、校验、命名，一次完成。
- **装完即用**：缺少 Typst 时首次排版自动下载安装（SHA256 固定、可关），中文字体与 Typst 包随插件分发，
  填空笔记离线也能编译；`zju_doctor` 随时报告本机依赖状态。
- **自动 PDF**：写完讲义就在本地排同名 PDF（封面、目录、标题层级、居中公式、三线表、边注）；
  PDF 失败不影响 Markdown，Agent 只多收一行路径。
- **内容不丢**：字幕按分钟 / 逐句 / 分块读取；可读本地 PPTX / DOCX / PDF 课件校准术语；
  可选把课堂投影截图合成 PDF。
- **能动手复习**：可选「填空式学习笔记」——**基于 Typst scholia 模板排版的填空式学习笔记**；
  配色与段落规范由本项目定义，见 [scholia-notes 规范](skills/scholia-notes/references/typography-spec.md)。
- **隐私优先**：Cookie 不进工具参数与返回值，全输出脱敏；敏感文件拒绝；TLS 永不降级。
- **到处能用**：dsh 原生插件、标准 MCP、MiniMax Code 插件包、命令行四种入口。

## 安装

### 1. DeepSeek Harness（dsh）

从 npm 安装（推荐，2.1.0 起）：

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
  「浙大智云课堂讲义」一栏要重启后才会出现。原因见 [技术细节](docs/technical.md#2-安装形态与依赖)。
- 不要只解压 zip 让 dsh 加载（peer 依赖由 pnpm 在 `dsh plugin add` 时安装）。

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
      "timeout": 120000
    }
  }
}
```

`server.mjs` 会自己找 Python（`ZJU_PYTHON` → `python3` / `python` / `py -3`，要求 3.9+）。
Claude Code 一行接入：

```bash
claude mcp add zju-lecture node /绝对路径/dsh-zju-lecture-note/server.mjs
```

### 3. 其它入口

```bash
# MiniMax Code 插件包
python tools/build_plugin.py --install --zip

# 命令行
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
- 字幕先匿名；HTTP 401/403 时自动用本机登录态重试一次。一次只抓一节课，不要批量抓取。

### 阅读版 PDF

`zju_write_note` 写完 Markdown、修完公式、跑完校验之后，会把**同一份内容**排成同名 PDF，
Agent 只多收到一行 `PDF: <路径>（N 页）`。失败时 Markdown 照常写入，只回一行 `PDF 跳过: …`。
关掉自动排版（`renderPdf`）后只交付 Markdown；已有讲义可用 `zju_check_note(pdf=true)` 补排。

讲义里可以直接写这些标记：

| 你写 | 得到 |
| :--- | :--- |
| `[直觉]` / `[定义] 标题 —— 正文` / `[定理]` / `[例]` | 淡彩方框（青绿 / 蓝 / 琥珀） |
| `[证明]` | 斜体 `Proof.` + **块末** qed |
| `[练习]` | 带 3 行书写横线的练习块 |
| `[边注]` / `[边注!]` | 右侧留白栏的边注 |
| `[强调]` / `[易错]` / `[弱注]` / `[分隔]` | 行内高亮 / 提示 / 弱化 / 分隔 |
| `____` / `[缺口: …]` | 灰色填空线 / 留白 |
| `<def:x>` + `@def:x` | 编号与回指（原生交叉引用） |

方框与 `[证明]` 是「块」不是「一行」：从标记行排到下一个标记 / 标题 / 整行粗体的小标题，
块里的空行是段落分隔，`$$…$$`、列表、表格都留在装置里 —— 证明的 qed 因此落在真正的结尾。
语义、预算（每节方框 ≤ 2 个）与数学写法由
[格式规范](skills/scholia-notes/references/format-spec.md) 统一规定；字体、字号、版心、
边注等排版数值以[排版规范](skills/scholia-notes/references/typography-spec.md) 为唯一真相源；
两条链路共用同一套参数。

### 填空式学习笔记（可选）

打开 `enableStudyNotes` 后，`zju_build_study_notes` 产出**基于 Typst scholia 模板排版的
填空式学习笔记**：`mode=draft` 生成填空底稿，`mode=patch` 把一批挖空/标记一次写回，
`mode=compile` 排成 PDF + 逐页 PNG。
**配色与段落规范由本项目定义**，见
[scholia-notes 规范](skills/scholia-notes/references/typography-spec.md)。
工具只做搬运与排版，哪句是定理、哪里挖空仍由你判断——自动挖空等于替读者决定「考什么」。

字体：两条 PDF 链路默认都用随包的 **Notes Kai SC**（LXGW WenKai / 霞鹜文楷的
GB2312 子集）与 **Notes Serif SC**（Noto Serif SC 的 GB2312 子集），均为 SIL OFL，
不再依赖系统商业字体；生僻字回退到 Noto / Source Han（OFL）。对外分发 PDF 前按
[排版规范 §8](skills/scholia-notes/references/typography-spec.md) 用 `pdffonts`
确认没嵌入 SimSun / KaiTi 等系统商业字体。

### 投影截图（可选，默认关闭）

先打开 `enableSlides`（总开关），再决定 `embedSlideImages`（是否把截图插进讲义）。
打开后 Agent 会把截图下载到 `ppt-assets/<sub_id>/images/`，挑 **3–8 张**关键页写进讲义。
投影接口只返回截图，没有文字层 / OCR；需要幻灯片原文请提供原始 `.pptx`。
登录态优先读本机 Edge，也可用 `ZJU_COOKIE` / `ZJU_COOKIE_FILE`（**不要把 Cookie 贴进对话**）。

## 工具一览

dsh 默认注册 **6 个**核心工具（含依赖自检 `zju_doctor`）；打开填空笔记 +1、投影 +1、登录辅助 +2，**全开 10 个**。
关掉的模块不占工具列表、不加载代码。

| 工具 | 用途 | 默认 |
| :--- | :--- | :--- |
| `zju_parse_url` | 解析回放链接，取 `sub_id` / `course_id` / `tenant_code` | 开 |
| `zju_fetch_transcript` | 抓整节课或指定时间段的语音字幕（按分钟 / 逐句 / 分块 / JSON） | 开 |
| `zju_extract_courseware` | 提取本地 PPTX / DOCX / TXT / MD / CSV / JSON / PDF 文本 | 开 |
| `zju_check_note` | 检查 / 修复**已有**讲义；`pdf=true` 重排 PDF | 开 |
| `zju_write_note` | 写入讲义：自动命名、拒绝静默覆盖、修公式、校验、自动排 PDF | 开 |
| `zju_doctor` | 检查 Python / Typst / 字体 / 包；`install=true` 装 Typst，`login=true` 检查登录态 | 开 |
| `zju_build_study_notes` | 讲义 → 填空底稿 →（批量挖空）→ scholia PDF + 逐页 PNG | 关（`enableStudyNotes`） |
| `zju_fetch_slides` | 抓投影截图清单，可选下载并合成 PDF | 关（`enableSlides`） |
| `zju_get_video_url` | 解析回放 MP4 直链（供下载或 Whisper 重识别） | 关（`enableLoginTools`） |
| `zju_read_browser_cookie` | 读本机 Edge 登录态并缓存到服务端内存（只回名称与长度） | 关（`enableLoginTools`） |

## 设置

dsh 的六个开关在 **设置 → 左侧导航「浙大智云课堂讲义」**（独立一栏，不占通用设置），
按「核心链路 → 阅读输出 → 环境与依赖 → 主动回忆 → 课堂投影 → 登录辅助」分组，并有三枚预设：
**省 Token / 复习模式 / 全功能**。

同一页也在**左侧栏的「智云讲义」一行**（`插件` / `自动化任务` 下面）：点它直接在主区域打开，
不必先进设置。左栏入口与设置页共用同一份配置和同一个控制器，改哪边都一样；
侧边栏收起时它只显示图标，悬停给出同一个名字。

| 设置 | 作用 | 默认 |
| :--- | :--- | :--- |
| `renderPdf` | 写完讲义自动排同名 PDF | 开 |
| `typstAutoInstall` | 缺少 Typst 时自动下载安装（约 20 MB，SHA256 校验） | 开 |
| `enableStudyNotes` | 填空式学习笔记（`zju_build_study_notes` + scholia Skill） | 关 |
| `enableSlides` | 投影抓取总开关（`zju_fetch_slides`） | 关 |
| `embedSlideImages` | 投影截图是否插进讲义（仅在总开关打开时有效） | 关 |
| `enableLoginTools` | 视频直链 / 读取 Edge 登录态工具；字幕鉴权由核心链路自动完成，不依赖此开关 | 关 |

MCP 对应：`ZJU_RENDER_PDF`、`ZJU_TYPST_AUTO_INSTALL`、`ZJU_ENABLE_STUDY_NOTES`、`ZJU_ENABLE_SLIDES`、
`ZJU_EMBED_SLIDES`、`ZJU_ENABLE_LOGIN_TOOLS`（只控制登录辅助工具；字幕鉴权不受影响）。
另有 `ZJU_TYPST_BIN`（指定已有 Typst）与 `ZJU_TYPST_MIRROR`（下载镜像前缀）。

## 常见问题

**设置里找不到「浙大智云课堂讲义」一栏？**
完全重启 DeepSeek Harness。dsh 在启动时缓存 `dsh.client` 元数据，刷新页面或只重装插件都不够。

**返回 `PDF 跳过: …`？**
先让 Agent 跑 `zju_doctor`：它会报 Typst 版本 / 路径 / 来源、字体与 Typst 包；`login=true` 可额外检查登录态。
缺少 Typst 时 `zju_doctor(install=true)` 会下载并校验安装；也可以自己装好（`typst --version` 能跑）
后用 `zju_check_note(pdf=true)` 给已有讲义补排。Markdown 本身不受影响。
若返回 `PDF 跳过: 找不到 typst：…` 且自动安装被关闭（`ZJU_TYPST_AUTO_INSTALL=0`），
打开设置里的「自动安装 Typst」或手动安装即可。

**看不到投影 / 登录工具？**
它们默认关闭。到设置里打开 `enableSlides` / `enableLoginTools` 并完全重启 dsh。字幕工具常驻，鉴权由字幕工具自动完成，不需要开启登录辅助。

**只解压 zip 启用，报 `Cannot find package '@deepseek-ai/schemastery'`？**
那是 peer 依赖，由 pnpm 在 `dsh plugin add` 时装进 profile。请用 npm 包名、`github:` 或 `file:` 方式安装。

**市场安装报 `connection to github.com timed out after 5000ms`？**
这是 dsh 宿主在 pnpm 启动前做 GitHub 连通性预检（`git ls-remote`，默认 5 秒）超时，不是插件本身报错。
优先用上面的 npm 命令安装，不经过 GitHub；必须走 GitHub 源时，先确认
`git ls-remote https://github.com/chenqianyu486-sys/dsh-zju-lecture-note HEAD` 能在 5 秒内返回。
超时的话给 git 配代理，并让 dsh 进程能读到 `HTTPS_PROXY` / `HTTP_PROXY`（它不读 Windows 系统代理）；
或在该 profile 的 `cordis.patch.yml` 里把 `plugin-manager` 的 `githubConnectionTimeoutMs` 调大后重启。

**字幕抓取失败（401/403 / 证书 / 代理）？**
HTTP 401/403 表示匿名请求被拒：确认已在 Edge 登录智云课堂，或配置 `ZJU_COOKIE_FILE`；插件会自动重试一次。读不到凭据 / 遇到 ABE 时按诊断配置文件，不要反复重试、贴 Cookie 或直接归因校园网。
CLI 默认自动重试，`--no-login` 可关闭，`--cookie-file` 可指定本地文件；证书校验不降级，信任库与代理诊断见 [SECURITY.md](SECURITY.md)。

## 隐私与安全

- **Cookie 不是工具参数**：字幕 / 投影 / 视频直链 / 读 Cookie 工具均不接受 Cookie；登录态只能由本地配置或本机 Edge 提供。
- **Cookie 不回显、不落盘**：读 Cookie 只返回名称、数量、长度与来源类别，
  所有输出经过 redactor；必须复制 Edge 数据库时用 0600 临时文件，读完覆写并删除。
- **网络边界**：只允许 `classroom.zju.edu.cn` 与 `https://*.zju.edu.cn` 截图主机，跨域重定向拒绝；证书校验不降级。
  字幕请求不发 Cookie 头，鉴权只向 `classroom.zju.edu.cn` 发 Bearer；除上述鉴权重试外，仅瞬时故障重试。
- **本地文件有边界**：课件 / 讲义工具只接受指定扩展名，拒绝凭据、私钥与浏览器数据。
- **可机器验证**：`python tools/privacy_scan.py` 扫描工作区、git 历史与 npm 产物。

完整威胁模型见 [SECURITY.md](SECURITY.md)，实现细节见 [技术细节](docs/technical.md#8-隐私设计)。

## 许可与致谢

本插件以 MIT 许可证发布，改编自 [`nzw806/zju-lecture-summerizer-`](https://github.com/nzw806/zju-lecture-summerizer-)（MIT），
原项目的版权声明保留在 [LICENSE](LICENSE)。

**PDF 排版的上游模板**（特别感谢）：

- [`@preview/scholia`](https://typst.app/universe/package/scholia) **0.1.0**（MIT，© Eric Yang / 杨星宇，
  仓库 [`Eryc123Y/scholia`](https://github.com/Eryc123Y/scholia)）：**基于 Typst scholia 模板
  排版的填空式学习笔记**的排版引擎（knot / note / 边注 / 封面 / 淡彩主题）；配色与段落规范
  由本项目定义，见 [scholia-notes 规范](skills/scholia-notes/references/typography-spec.md)。
  **该包及其依赖已随本仓库分发（vendored）**在 `zju_lecture/typst-packages/`，使填空笔记编译
  不再依赖 Typst 包注册表；逐包保留上游 `LICENSE` / `UNLICENSE` 与 `typst.toml`，删除 README
  与模板示例，并对 `src/fonts.typ` / `src/lib.typ` 打了补丁（见
  [`VENDORED.md`](zju_lecture/typst-packages/VENDORED.md)）。
  本插件的阅读版讲义 PDF 使用自研模板（`zju_lecture/handout_prelude.typ`），
  **视觉设计参考了它的浅色 notes 主题**，未拷贝其源码。
- [`@preview/frame-it`](https://typst.app/universe/package/frame-it)（MIT，© Marc Thieme）、
  [`@preview/marginalia`](https://typst.app/universe/package/marginalia)（UNLICENSE）、
  [`@preview/theoretic`](https://typst.app/universe/package/theoretic)（UNLICENSE）、
  [`@preview/showybox`](https://typst.app/universe/package/showybox)（MIT）与
  [`@preview/noteworthy`](https://typst.app/universe/package/noteworthy)（MIT）：scholia 的传递依赖，
  同样随包分发，版本与许可见 [`VENDORED.md`](zju_lecture/typst-packages/VENDORED.md)。
- 上游 scholia 声明自己是受 [`loom-notes`](https://github.com/Polaris-Aeterna/loom-notes)
  设计启发的独立重写（XeLaTeX，MIT，未复用源码）；本仓库也未分发它。
- 「scholia」一词仅用于指代所依赖的 Typst 包；本插件与 Eric Yang 无隶属关系，也未获其背书。
  逐条归属与「未拷贝代码」边界见 [ATTRIBUTION.md](ATTRIBUTION.md) 与
  [THIRD_PARTY_NOTICES.md](skills/scholia-notes/THIRD_PARTY_NOTICES.md)。

**随包中文字体**：`zju_lecture/fonts/NotesKaiSC-Subset.ttf` 是
[LXGW WenKai](https://github.com/lxgw/LxgwWenKai)（霞鹜文楷）v1.530 的 GB2312 子集，
`NotesSerifSC-Subset.ttf` 是 [Noto Serif SC](https://fonts.google.com/noto/specimen/Noto+Serif+SC)
的 GB2312 子集，均为 SIL OFL 1.1；两个字体都已改名以免与本机完整字体冲突。
`OFL.txt` / `OFL-Kai.txt` 与 `FONT-NOTICE.md` 必须随字体一起分发。

其他项目：

- [`PeiPei233/zju-learning-assistant`](https://github.com/PeiPei233/zju-learning-assistant)（ZLA，MIT）：
  智云课堂 / 学在浙大 API 流程的原始实现，本插件与参考 CLI 的共同上游。
- [`8eoyw/zju-learning-cli`](https://github.com/8eoyw/zju-learning-cli)（MIT）：投影 PPT 管线的参考
  （`_token` → Bearer、分页去重、截图合成 PDF），本仓库按零第三方依赖重新实现，未拷贝代码。
- [Typst](https://typst.app)（Apache-2.0）：两条 PDF 链路的排版编译器。插件**不分发** Typst 二进制：
  缺少时从官方 GitHub Release 下载到用户缓存目录，按仓库内固定的 SHA256 校验后再使用。
- [`certifi`](https://github.com/certifi/python-certifi) 与 Mozilla CA 证书库：随包 `cacert.pem` 的来源。
- 以及为本插件提交 issue、做实地运行反馈、审查代码与文档的同学。

## 文档

| 文档 | 内容 |
| :--- | :--- |
| [docs/technical.md](docs/technical.md) | 技术细节：目录结构、隐私实现、PDF 排版、标记语法、开发测试、发布流程 |
| [CHANGELOG.md](CHANGELOG.md) | 版本历史 |
| [SECURITY.md](SECURITY.md) | 威胁模型、Cookie 生命周期、已知边界 |
| [ATTRIBUTION.md](ATTRIBUTION.md) | 逐文件来源、第三方许可、参考实现边界 |
| [format-spec.md](skills/scholia-notes/references/format-spec.md) | 规范性文件：Markdown → PDF 装置的语义对应、预算、配色与字体 |

仅供个人学习使用：只抓取本人有权限访问的回放，Cookie 属个人凭证，不要外传。

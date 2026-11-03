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
│   ├── client.js                  # 浏览器半边：设置页「浙大智云课堂讲义」
│   ├── tools.js                   # 生成物：dsh 工具定义
│   └── tools.schema.json          # 生成物：工具定义快照（供测试比对）
├── .minimax-plugin/plugin.json    # MiniMax Code（MCode）插件清单
├── zju-lecture.mcp.json           # MCP 服务器定义（stdio → node ./server.mjs）
├── server.mjs                     # 启动器：解析 Python 解释器并拉起 MCP 服务
├── mcp_server.py                  # MCP stdio 服务器（JSON-RPC 2.0，隐私边界在这里）
├── zju_lecture/                   # 核心库（纯标准库）
│   ├── client.py                  # 智云课堂 API 客户端（TLS 校验 + 同域重定向）
│   ├── cookies.py                 # Edge Cookie 读取与安全清理
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
  → zju_fetch_transcript（公开字幕接口，按分钟 / 逐句 / 分块 / JSON）
  →（可选）zju_extract_courseware（本地课件校准术语）
  → Agent 写 Markdown
  → zju_write_note：命名 → 修公式 → 校验 → 写文件 → 排版同名 PDF
  →（可选）zju_build_study_notes：讲义 → 填空底稿 → scholia PDF + 逐页 PNG
```

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
（只影响传输路径，哈希仍按清单校验）。`zju_doctor` 报告上述全部状态，`install=true` 立即重试安装。

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

**Python 探测顺序**：插件配置项 → 环境变量 `ZJU_PYTHON` → DeepSeek Harness 自带 Python →
PATH 上的 `python3` / `python` / `py -3`。

**client 元数据在 Host 启动时缓存**：`dsh.client` 新增或修改后，只重装插件、甚至刷新页面都不够，
必须**完全重启 DeepSeek Harness**；可在 `cordis_inspect_query` 的 `Slots` →
`factory:dsh-zju-lecture-note` / `settings.section` 验证。

## 3. 工具与开关分层

v2.0.1 起，「字幕 → 讲义 → PDF」主链路与所有可选能力解耦。每个模块有自己的工具、
Skill 附录和系统提示；关掉就**不存在**，不占工具列表、不读登录态、不加载代码。

| 分层 | 工具 | 依赖 | 默认 |
| :--- | :--- | :--- | :--- |
| **字幕主链路** | `zju_parse_url` / `zju_fetch_transcript` / `zju_extract_courseware` / `zju_check_note` / `zju_write_note`（含自动 PDF） | 公开字幕接口 + 本地文件 + 可选 Typst | 始终开启 |
| **填空笔记** | `zju_build_study_notes` + `scholia-notes` Skill | 本机 Typst | 关闭（`enableStudyNotes`） |
| **投影抓取** | `zju_fetch_slides` | 登录态 + 截图下载 + PDF 合成 | 关闭（`enableSlides`） |
| **投影插图** | （`zju_fetch_slides` 的子开关） | 依赖投影抓取 | 关闭（`embedSlideImages`） |
| **登录辅助** | `zju_get_video_url` / `zju_read_browser_cookie` | 本机 Edge 或 `ZJU_COOKIE` / `ZJU_COOKIE_FILE` | 关闭（`enableLoginTools`） |

- dsh 默认注册 **5** 个工具；`enableStudyNotes` +1、`enableSlides` +1、`enableLoginTools` +2，
  全开 **9** 个。
- MCP 未设置新变量时保持旧行为（10 个）；仓库自带的 `zju-lecture.mcp.json` 默认关掉三个可选模块（6 个）。
- 关闭时：不注册对应工具、不加载对应模块、Skill 不追加对应附录；系统提示会说明
  「这个模块已关闭」，Agent 不会调用或假装调用。
- 实现上，`lib/index.js` 用 `registerableTools()` 过滤；`mcp_server.available_tools()`
  同步过滤 `tools/list`；直接调用会抛 `SlidesDisabledError`（RPC 侧是 `isError`）。
- `zju_lecture/__init__.py` 用 PEP 562 懒导出 `download_slides` / `build_slides_pdf` / `SlideError`；
  `mcp_server.py` 只在进入 `zju_fetch_slides` 分支时才导入 `zju_lecture.slides`
  （纯字幕进程的 `sys.modules` 里不会出现截图模块，有子进程测试守住）。
- dsh 单独把 `zju_fetch_slides` 的超时提高到 600s（下载整节课截图用），其他工具仍用配置值。
- 投影抓取与填空笔记互不依赖；登录辅助也与投影抓取解耦——投影工具会自己解析登录态。

### 环境变量

| 变量 | 作用 |
| :--- | :--- |
| `ZJU_PYTHON` | 指定 Python 解释器 |
| `ZJU_WORKSPACE` | 相对路径的解析根；dsh 插件自动传入 session workspace |
| `ZJU_BACKUP_DIR` | `zju_check_note` / `zju_write_note` 的备份目录（默认系统临时目录） |
| `ZJU_COOKIE` / `ZJU_COOKIE_FILE` | 登录态（仅投影 / 视频直链需要） |
| `ZJU_RENDER_PDF` | 默认 `0`（MCP）；对应 dsh `renderPdf`（默认开） |
| `ZJU_TYPST_AUTO_INSTALL` | 缺 Typst 时自动下载安装（默认 `1`；dsh 对应 `typstAutoInstall`） |
| `ZJU_TYPST_BIN` | 指定已有 Typst 可执行文件（优先级最高） |
| `ZJU_TYPST_MIRROR` | Typst 下载 URL 的镜像前缀，例如 `https://ghfast.top/` |
| `ZJU_TYPST_CACHE` | 覆盖 Typst 缓存目录（默认用户缓存；测试与换盘时用） |
| `ZJU_ENABLE_STUDY_NOTES` / `ZJU_ENABLE_SLIDES` / `ZJU_EMBED_SLIDES` / `ZJU_ENABLE_LOGIN_TOOLS` | 可选模块开关 |
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
  - 版心不对称：左 2.4cm / 右 3.9cm，右侧 2.6cm 是边注栏；封面与目录不占页码，正文第一页从 1 起。
  - 一级标题：灰蓝编号 + 蓝色标题 + 1.1pt 细线；方框淡彩底 + 左侧 2.2pt 竖线、无圆角；
    证明以斜体 `Proof.` + 行末 qed。
  - 正文参数：`leading 0.72em`、`spacing 0.95em`、段首 `#h(2em)` 顶首行、公式块 `1.6em`。
  - `par.first-line-indent` **不可靠**：它只在「前一个兄弟元素是段落」时生效，
    标题 / 块 / 图 / 公式后的段落一律不缩进 ⇒ 改用行内 `#h(2em)`。
  - 块级公式的上下间距吃 `par.spacing`，压段间距会把公式压到下一段上 ⇒ 用
    `#show math.equation.where(block: true): set block(above: 1.6em, below: 1.6em)` 解耦。
  - 边注用 `box(width: 0pt, context { let p = here().position(); place(top + left, dx: page.width - p.x - 2.6cm - 0.6cm, …) })`：
    直接 `context` + `place(top + right)` 会把边注甩到页面顶端。
- **标记语法**（转义前处理；`____` 先于转义，否则会被变成 `#fillin` 后漏掉）：

  | 标记 | 装置 |
  | :--- | :--- |
  | `[直觉]` | `#note`（青绿淡底） |
  | `[定义] 标题 —— 正文` / `[定理]` / `[命题]` / `[例]` | 带标签的方框 |
  | `[证明]` | 斜体 `Proof.` + qed |
  | `[练习]` | `#yourturn` + 3 行 `#workspace(n: 3)`（练习块里的短 `____` 一律丢弃） |
  | `[边注]` / `[边注!]` | 右侧留白边注（`[边注!]` 带强调） |
  | `[强调]` / `[易错]` / `[弱注]` / `[分隔]` | 行内高亮 / 提示 / 弱化 / 分隔线 |
  | `____` | `#fillin(width: 2.2cm)`（灰色，提示留给读者写） |
  | `[缺口: …]` | `#gap` 留白 |
  | `<label>` / `@label` | 两遍扫描后生成原生交叉引用 |

  标题手写的编号（`1.` / `1.2` / `一、` / `（三）`）**一律剥掉**，编号只由 Typst 生成。
- **数学**：与填空笔记共用 `study_notes.latex_to_typst`：`pmatrix` / `bmatrix` / `cases` / `aligned`
  机械转成 `mat` / `cases` / 对齐换行；多字母标识符（`AC`、`e^{-st}`、`BVP`）按规则转成
  直立或拆乘积，避免 Typst 报 unknown variable。
- **方框预算**：编译报告里给正文段落数、方框数、方框:正文比值（1:8 以内稳，超过 1:4 告警）、
  逐节方框数。规范要求每节方框合计 ≤ 2，框的唯一正当理由是「后面会被回指」。

### 配色

浅色 `soft-palette` 的**唯一权威来源**是 `zju_lecture/prelude.typ`：

| role | 色值 | 对比度（对 `bg`） |
| :--- | :--- | :--- |
| `bg` | `#FDFDFB` | 1.00 |
| `ink` | `#1A1A1C` | 17.06 |
| `thm` | `#33609B` | 6.27 |
| `def` / `tag` / `keyword` | `#20705F` | 5.82 |
| `eg` | `#8F6218` | 5.25 |
| `warn` | `#6350A8` | 6.36 |
| `muted` | `#6F7683` | 4.49 |
| `fillin` | `#8E97A3` | 2.90 |
| `rule` | `#93A6C4` | 2.43 |
| `hairline` | `#DBDFE6` | 1.31 |

- `handout_prelude.typ` 的 `#let palette` 与 `handout._PALETTE` 是**生成副本**：
  改色只改 `prelude.typ`，再跑 `python tools/sync_palette.py`，
  `--check` 校验三处逐角色一致（`tests/test_palette_sync.py` 也会跑）。
- 页面 `fill: palette.bg`；`handout._tint` 混向 `bg` 而不是纯白，才与 Typst `tint()` 同算法。
- 深色主题（slate）由上游 scholia 自带，本项目不注入 `use-palette`。
- 「极差 1.11」是四个强调色在对比度刻度上的**跨度**（6.36 − 5.25），不是比值；目标 ≤ 1.2。

### 字体与可再分发性

Typst 会把用到的字体子集内嵌进 PDF。两条 PDF 链路都优先使用**随包自带的 OFL 字体**：

| role | 首选 | 回退 |
| :--- | :--- | :--- |
| body / heading | `STIX Two Text`（SIL OFL） | Typst 内嵌 `Libertinus Serif` |
| math | `STIX Two Math` | `New Computer Modern Math` |
| mono | `DejaVu Sans Mono` | `Consolas` |
| 中文 | **`Notes Serif SC`（随包，OFL 子集）** | `Noto Serif SC` / `Source Han Serif SC`（OFL）→ `Songti SC` / `SimSun` |

- `Notes Serif SC` 是 Noto Serif SC 的 GB2312 子集 + 常用符号（约 7.5k 字，5.7 MB），**保留了
  `wght` 变量轴**，所以标题的 `weight: "bold"` 有真正的粗体面；生僻字逐字回退到系统字体。
- **改名是刻意的**：与用户本机完整版同名时 Typst 选哪个字体面不确定，也避免让人误以为是完整字体、
  避开 Noto / Source / ZJU 商标。
- 许可是 SIL OFL 1.1（无 Reserved Font Name）：允许子集化与再分发，但必须随附 `OFL.txt` 与版权声明，
  衍生字体继续以 OFL 分发，且不得单独售卖字体。相关文件在 `zju_lecture/fonts/`。
- `Optima` / `Avenir Next` / `Menlo` 等专有字体**不在生效的字体栈里**，只以注释形式留在模板中
  供本机还原上游观感；那种 PDF 不要再分发。
- 填空笔记通过 `fonts: (cjk: (...))` 把随包字体插到首位；上游包的 `note` / `sidenote` / `label-it`
  仍直接读包内字体表，改不到（已知限制）。
- 对外分发 PDF 前用 `pdffonts out.pdf` 核对一次：若出现 `SimSun` / `Microsoft YaHei` 等系统商业字体，
  说明生僻字回退到了它们，换一份完整 OFL 字体再排。

## 6. 填空笔记链路

`zju_lecture/study_notes.py` 负责两段：

- `mode=draft`：讲义 → 填空底稿（标题层级映射、标记位插入、LaTeX 数学 → Typst 数学）。
  标记位只插 `[直觉]` / `[练习]` / `[边注]`——`[定义]` / `[定理]` / `[证明]` 该不该用是内容判断，
  骨架不替使用者决定。
- `mode=compile`：底稿 → `main.typ` + `prelude.typ` → `out.pdf` + 逐页 `page-N.png`，
  并报告编译错误、方框预算与悬空回指。

接口细节：

- 骨架**不会**替使用者插 `[定义]/[定理]/[证明]`——那三个框该不该用是内容判断。
- 底稿可以写 `<!-- … -->` 注释，转成 Typst 块注释，不渲染、也不计进正文段落。
- 数学转换是**幂等**的（`_looks_like_typst_math`）：`build_draft` 转一次、`render_typst` 再转一次
  不会把 `sum` 拆成 `s u m`。
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

1. 来源只有本地：内存缓存 → `ZJU_COOKIE` → `ZJU_COOKIE_FILE` → 本机 Edge；
2. 校验：拒绝换行（HTTP 头注入）、空 name、超长；不合法只返回原因，不回显内容；
3. 使用：只放进发往 `classroom.zju.edu.cn` 的请求头；跨域重定向拒绝；
4. 缓存：仅 Python 子进程内存；
5. 回显：没有；工具 schema 中没有 cookie / reveal / domain 参数；
6. 日志：所有 stdout / stderr 经过 `SecretRedactor`；
7. 临时文件：只读打开优先；必须复制时连同 `-wal` / `-shm` 一起复制（刚登录的行可能还在 WAL 里），
   权限 0600，读完覆写并删除。

Cookie 不是工具参数：`zju_fetch_slides` / `zju_get_video_url` 不接受 cookie 参数，
`zju_read_browser_cookie` 也没有参数；登录态只能由本地配置或本机 Edge 提供。

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
  证书校验失败**不重试**。
- 跨域 302 直接拒绝，避免 `urllib` 把 `Cookie` 头重发到第三方域。
- 投影截图只允许 `https://*.zju.edu.cn`；ZJU 的 `http://` 自动升级 HTTPS；
  Cookie 只给 ZJU 图片主机、不发 Bearer；跨主机重定向剥离凭据；写盘限制在工作区。

### 数据会离开本机的部分

字幕与课件文本会作为工具结果进入宿主模型上下文，由你选择的模型提供方处理——这是使用大模型
整理讲义的固有代价。插件本身不收集、不额外上传、不写遥测、不写用户目录。

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
node tests/plugin_apply_smoke.mjs           # 插件形态：默认 6 工具 / 打开后 10 工具
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
阅读版 PDF 的标记装置与真实编译、配色三处一致与字体可再分发性、填空笔记链路。

> 测试中的 `subprocess` / 管道 / 临时文件在受限沙箱里可能被拒绝；这是环境限制，不是插件缺陷。

## 10. 发布流程

### npm / dsh 插件包

仓库根目录就是 npm 包（包名 `dsh-zju-lecture-note`），发布即发布这个仓库：

```bash
npm login                 # 首次发布前登录（交互式，需本人操作）
npm pack --dry-run        # 先看一眼会打进包里的文件清单
python tools/privacy_scan.py --tarball <生成的 .tgz>   # 发布前隐私闸门
npm publish               # 发布到 npm registry
```

`files` 字段是逐文件枚举的运行时清单（`lib/`、`mcp_server.py`、`zju_lecture/*.py`、`skills/`、
`SECURITY.md`、`CHANGELOG.md`、`docs/technical.md`……），**不要**改成整目录——
否则 `__pycache__/*.pyc` 会混进包里（`files` 的优先级高于 `.npmignore`）。

dsh 按 `peerDependencies` 校验运行时版本。若升级 dsh 后插件被跳过，请检查
`@deepseek-ai/dsh-*` 的 peer 范围，或按 dsh 提示使用 `dsh plugin allow-version` 做精确版本豁免。

### MCode 插件包

`python tools/build_plugin.py --install --zip`；运行时文件清单在 `PACKAGE_FILES` / `PACKAGE_DIRS`，
新增文档文件时记得同步，否则装好的包里会出现断链。

### 版本号

版本在**六处**对齐：`package.json`、`pyproject.toml`、`mcp_server.SERVER_VERSION`、
`.minimax-plugin/plugin.json`、两个 Skill manifest（由 `tools/build_skill_manifest.py` 生成）。
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
- **网络依赖**：离线时字幕抓取、讲义写入、填空笔记编译（已 vendor 包与字体）都可用；
  只有「首次安装 Typst」需要网络。
- **投影截图没有文字层 / OCR**：接口只返回图片。需要幻灯片原文时让用户提供 `.pptx` 走
  `zju_extract_courseware`；模型不能看图时 Agent 只列截图索引，不臆造内容。
- **Edge 登录态的两条死路**：Chromium 对 Cookie 数据库加独占锁；Edge 127+ 若启用应用绑定加密（ABE），
  v20 Cookie 连 DPAPI 也解不开。插件会读 `Local State` 判定 ABE 并直接指向 `ZJU_COOKIE_FILE`；
  读库兜底复制会带上 `-wal` / `-shm` 并让 SQLite 回放 WAL。
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
- **字幕接口公开，但请遵守平台条款**：一次一节课，不要批量抓取。

## 12. 上游与归属

本插件的来源、参考实现与「未拷贝代码」的边界见
[ATTRIBUTION.md](../ATTRIBUTION.md)（逐文件来源）与
[skills/scholia-notes/THIRD_PARTY_NOTICES.md](../skills/scholia-notes/THIRD_PARTY_NOTICES.md)
（Typst 包、字体、配色归属）。

其中与 PDF 模板直接相关的：

- `@preview/scholia` 0.1.0（MIT，© Eric Yang）是填空笔记链路的排版引擎，
  **已随本仓库分发（vendored）**在 `zju_lecture/typst-packages/`，逐包保留上游许可与 `typst.toml`；
- 其余传递依赖（frame-it / marginalia / theoretic / showybox / noteworthy）同样随包分发，
  版本与许可见 `zju_lecture/typst-packages/VENDORED.md`；
- 阅读版讲义模板 `handout_prelude.typ` 是本项目自研、自包含的重写，视觉上参考 scholia 的
  浅色 notes 主题（配色角色、装置语义），**未拷贝上游源码**；
- 上游 scholia 声明自己是受 `loom-notes` 设计启发的独立重写（未复用源码），本仓库亦未分发它；
- 本插件与 Eric Yang 无隶属关系，也未获其背书；「scholia」一词仅作指示性使用。

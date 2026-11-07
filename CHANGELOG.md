# 更新日志

版本号在 `package.json`、`pyproject.toml`、`mcp_server.SERVER_VERSION`、
`.minimax-plugin/plugin.json`、`adapters/claude_code/plugin.json` 与四个 Skill manifest
共九处对齐。

## 2.2.7 — 2026-11-07

### 设置（dsh 图形化界面）

- **设置保存后立即对 Agent 生效，不再要求重启**：此前 `.volatile()` 字段保存时 dsh 只更新引用，
  不重新执行 `apply()`；插件读到的仍是启动时的工具集、Skill、系统提示词与 Python 子进程环境。
  现在监听 `loader/volatile-update`，重新同步工具注册、随包 Skill、提示词（`text` 改为每次组装
  重新读取配置的 thunk），并让已启动的 Python 子进程作废，下一次调用用新环境变量拉起。
- **补齐设置项**：`python`（Python 解释器）、`timeoutMs`（工具超时）、`registerSkill`（注册随包
  Skill）原先只在 Config schema 里、没有 `.volatile()`，因此不会出现在设置页；现在与
  `renderPdf` / `enableStudyNotes` / `enableSlides` / `embedSlideImages` / `enableLoginTools`
  一样可写。新增 `typstPath`（固定 Typst 可执行文件）与 `typstMirror`（GitHub 下载镜像前缀），
  对应既有的 `ZJU_TYPST_BIN` / `ZJU_TYPST_MIRROR`。
- 设置页新增「环境与依赖」的两个输入框与「高级」分组（解释器 / 超时 / Skill 开关）；
  「全功能」预设同时打开 `embedSlideImages`；页脚说明改为「保存后立即同步，下一轮可用」。
- **设置页视觉收敛**：一键配置以下不再使用卡片方框，改为灰色横线分隔分组；组内设置项左缩进
  20px；顶部介绍区去掉渐变与边框；设置项文案去重并缩短（同一信息只出现一次）。
- `zju_doctor` 的模块状态仍取自子进程环境；设置变更后子进程重建，因此报告与实际开关一致。
- 回归：`tests/plugin_apply_smoke.mjs` 覆盖「引用变更 → 工具 / Skill / 提示词 / 超时同步」；
  `tests/client_settings_smoke.mjs` 覆盖字符串与数字字段写入；新增
  `tests/test_settings_v227.py` 静态约束（所有字段 `.volatile()`、热更新监听、环境变量映射）。

### Security

按 2026-11-06 的只读安全审查结论逐项修复（分支 `fix/security-audit-2026-11`）。
详细威胁模型、边界与逐条验证见 `SECURITY.md` 第 7 / 9 / 10 节。

**P0 — 可被直接利用**

- **7.1 会话工作区隔离**（`c69fbdf`）：bridge 改为按绝对 workspace 维护
  `Map<key, WorkspaceSession>`（LRU 2），每个会话独立 cwd / `ZJU_WORKSPACE` / pending；
  删除 `PLUGIN_ROOT` 回退，工作区缺失或不存在时直接拒绝。
- **7.2 重定向与 SSRF**（`a45e551`）：按完整 origin（scheme + host + port）比较；
  拒绝 HTTPS→HTTP、URL userinfo、IP 字面量、localhost 与私网；截图只跟随浙大主机，
  跨 origin 剥离 Cookie / Authorization / Proxy-Authorization，阻断原因写入 diagnostics。
- **7.3 工作区外读写**（`0d7f037`）：新增 `require_workspace_path()`（resolve → realpath →
  工作区 → guard → 写入复检），`zju_extract_courseware` / `zju_check_note` /
  `mode=patch` 全部接入；外读需显式 `allow_outside_workspace=true` 且首行标注。
- **7.8 Typst 封面注入**（`25862cb`）：拆 `escape_typst_text()` / `escape_typst_string()`；
  封面改 `#scholia-cover(title: "…", …)` 命名参数，值按字符串字面量转义。

**P1 — 凭据、权限与资源**

- **7.4 镜像 URL 脱敏**（`db46f38`）：`_redact_url()` 去掉 userinfo / query / fragment，
  describe / progress / 异常全走脱敏；bridge.js 对 Python stderr 再做一层 JS 脱敏。
- **7.5 隐私扫描器掩码**（`d6f0668`）：默认只输出 path:line、规则名与命中长度；
  `--show-excerpt` 才输出前后各 6 字符、中间 `***` 的摘录；JSON 默认不含 excerpt。
- **7.6 临时文件与备份权限**（`2f2de09`）：session / 截图 / PDF 统一 `mkstemp` +
  `os.replace`；备份目录 0700、文件 0600、随机文件名；写入前 `lstat` 拒绝符号链接。
- **7.9 资源上限**（`b3864a6`）：课件单成员 16 MiB / 合计 64 MiB 预检；PNG 用
  `decompressobj(max_length)`；截图总量达到上限即停止；Typst 下载 256 MiB 上限并删半成品；
  tar 拒绝符号链接 / 硬链接。

**P2 — 入口、副作用与文档**

- **7.7 参数白名单**（`ea2f6d6`）：`handle_tool_call` 以 `inputSchema.properties` 为白名单，
  未知键直接拒绝，工具不执行，错误只含键名。
- **副作用确认**（`d7ccae0`）：`zju_login(clear=true)`、`zju_doctor(install=true)`、
  `zju_fetch_slides(download=true)` 必须同时传 `confirm=true`，否则不产生任何副作用。
- **CLI 与依赖**（本次提交）：`zju-lecture cookie --reveal` 在非 TTY 下拒绝、交互式需输入
  `yes`；`pypdf` 收紧为 `>=4.0,<8`；补 `package-lock.json` 使 `npm audit` 可运行。
- **文档**：`SECURITY.md` 第 7 节改为逐条「修复 commit + 回归测试」，新增第 9 节
  「工作区边界」与第 10 节「重定向 origin 校验与 SSRF」。

验证：734 tests OK（skipped=6）；`node tests/bridge_smoke.mjs` / `bridge_workspace_smoke.mjs` /
`bridge_workspace_isolation.mjs` 均 `ok:true`；`python tools/privacy_scan.py` 通过；
`npm pack --dry-run` 文件清单无临时 / 备份产物。

## 2.2.6 — 2026-11-06

- **修复上下标里的符号名被逐字母拆开**（实地会话 `session-42baa52c` 的讲义截图）：
  `$29^{\circ}$` 排成 `29^(c o m p o s e)`，PDF 右上角直接印出单词 `compose`。
  同一类错误波及**所有**多字母符号名：`x^{\alpha}` → `(a l p h a)`、
  `x_{\theta}` → `(t h e t a)`、`x^{\pi}` → `(p i)`。
  拆词规则现在只作用于**没转换过**的裸字母串（`a_{ij}` → `a_(i j)` 照旧），
  Typst 自己认得的名字按 `_TYPST_BARE_NAMES` 原样放行。
- **`\circ` 在上下标里转成 `degree`**：LaTeX 的 `29^\circ` 是角度，不是复合运算
  （`f\circ g` 仍是 `compose`）。不带花括号的写法也补括号——
  `29^\circ`、`\sum_{n=1}^\infty` 现在都能正常排；`x_1` / `a_n` 保持原样。
- **`\left` / `\right` 不再吞分隔符**：`\left\lvert … \right\rvert`、
  `\left\| … \right\|`、`\left\lVert … \right\rVert` 原先整段消失（绝对值与范数
  竖线没了），`\left.` 还会把那个点印进正文。顺带补上 `\lVert` / `\rVert` / `\|` 的映射。
- **尺寸命令静默丢弃**：`\big` / `\Big` / `\bigl` / `\Bigr` … 以前会印出单词 `big`；
  `\%` 也不再被 `note_lint` 误报成「未映射的 LaTeX 命令」。
- 回归 `tests/test_script_symbols_v226.py`（19 条），其中两条是通则：
  「符号表里每个多字母值放进上下标都不许被拆」与「转换两遍 == 转换一遍」。
- 验证：652 tests OK（skipped=2）；讲义 PDF 重排 0 error，页面上 `sin 29°`、
  `(1+x)^α`、`|Δx/x₀|` 均正常。

## 2.2.5 — 2026-11-06

- **默认安装即可用**：字幕鉴权改为核心链路的一部分。保留 `classroom.zju.edu.cn`，先匿名；
  仅 HTTP 401/403 时自动读取本机登录态、解析 Bearer 重试一次，不再要求开启登录辅助开关。
  字幕不发 Cookie 头，不用模型传凭据；`enableLoginTools` 只控制视频直链与读 Cookie 工具。
- **兼容老课程字幕**：`trans_type=ai` 返回 `time` / `zhtext` / `entext` 而非 `BeginSec` / `Text`，
  现在以第一条时间戳为相对零点换算秒数，旧课程也能生成讲义。
- **错误诊断更准确**：区分 HTTP 拒绝、接口业务错误与凭据读取失败；不再把 403 直接归因校园网。
  读不到凭据 / 遇到 ABE 时调用 `zju_login` 打开独立登录窗口，不索要 Cookie；
  代理 URL 的 userinfo 在诊断中掩码。
- **用户引导**：README 首屏说明首次登录与 401/403 处理；插件设置页、Skill 同步更新；
  `zju_doctor(login=true)` 可选检查登录态与 Bearer 可用性，默认不读取凭据。
- **新增用户命令**：`/zju-lecture-summarizer-help` 面向登录辅助与查错（401/403、登录态、
  代理、Typst/PDF、工具开关）。它只对用户命令可见、不进入模型技能目录，且明确禁止索要或回显凭据。
- **CLI 默认自动重试**：`fetch` 在 401/403 后自动使用本机登录态；`--no-login` 可关闭，
  `--cookie-file` 可指定本地文件，不新增明文 token 参数。

### 一键登录窗口（2026-11-06 追加，仍在 2.2.5）

**不再让用户开开发者工具配 Cookie。**

- **`zju_login` 常驻工具**：字幕 / 投影遇到 401/403、或本机 Edge 因 ABE 无法读取时，
  插件用独立浏览器 profile 打开登录窗口（不碰日常 Edge）。用户正常登录（SSO / 2FA 由页面处理），
  插件通过 `127.0.0.1` 随机端口从浏览器进程内读取 Cookie，成功后自动关闭窗口。
- **登录态安全保存**：只保存 Cookie（不保存账号密码），Windows 用 DPAPI 绑定当前用户，
  macOS / Linux 用 0600 文件；`zju_login(clear=true)` 一并删除登录态与独立浏览器配置。
  登录态失效时自动清除，下次从真正的登录页开始，不重放死 Cookie。
- **新的解析顺序**：内存缓存 → `ZJU_COOKIE` → `ZJU_COOKIE_FILE` → `zju_login` 登录态 → 本机 Edge。
  `ZJU_COOKIE_FILE` 降为无图形界面服务器的高级兜底，普通用户不再需要手工配置。
- **跨平台**：Windows / macOS / Linux 均优先 Edge，其次 Chrome / Chromium；
  可用 `ZJU_BROWSER_BIN` 指定浏览器，`ZJU_LOGIN_DIR` 覆盖状态目录。
- **新用户命令** `/zju-lecture-summarizer-login`：只负责打开登录窗口或清除本机登录态。
  主 Skill 与 help Skill 同步改写 401/403 SOP，禁止索要 Cookie、密码或开发者工具内容。
- **工具集**：默认 7 个核心工具、全开 11 个；核心 Skill 3 个（主 Skill / help / login），
  填空模式再加 scholia-notes。设置页说明「登录入口始终可用」，`enableLoginTools` 只控制两个可选辅助工具。
- **回归**：新增 `tests/test_login_v225.py`（23 条），覆盖安全存储、Cookie 域过滤、
  URL 白名单、解析顺序、失效清除、`clear=true` 与无浏览器失败原因。

### 框的跨段边界（2026-11-06 追加，仍在 2.2.5）

修一个「框太长」的排版问题：2.2.4 让定理 / 定义 / 例跨段之后，旧规则只认标题、已知标记
与整行粗体，框会一路收到下一个标题，把后续讲解、`> [!IMPORTANT]` 提示块和结论整段吞进去。

- **新增五种收尾边界**：`>` 引用 / 提示块；以 `⚠` 开头的提醒段（qed 因此落在推导的
  最后一条公式之后，而不是列表末尾）；「粗体小标题 + 冒号」（可带时间码，
  `**矛盾从哪里来**` `[00:05]`：…）；没加粗的「短引导词 + 时间码 + 冒号」
  （`推导要点` `[00:43]`：…，证明块除外，避免 qed 停在半路）；未知的中文标记
  （如 `[推导]`）。普通段落、块级公式、列表、表格仍然留在框里，证明与例题的
  多段正文不受影响。
- **例题四段式例外**：`**题目**` / `**切入点**` / `**关键步骤**` / `**易错点**` 仍留在框内，
  不会被当成新的小节抬头。
- **「重点」不再套方框**：`> [!IMPORTANT]` 改成 `#keypoint` —— 规范蓝色
  （`palette.thm` / `#33609B`）的无框文字段落，标签「重点」加粗；阅读版与填空版一致。
  其余 alert（注意 / 说明 / 提示）保持原提示块 / 灰色引用。
- **未知标记不再印方括号**：`[推导] …` 按旧规范的 Proof 样式兜底（斜体 `Proof.` +
  块末 qed，跨段、不套框）；其余未知标记按「加粗小标题 + 正文」排。`note_lint`
  新增 `unknown_marker` 提示，引导改成已支持的标记。
- 两条链路（阅读版讲义与填空笔记）共用 `study_notes.block_boundary()`；
  回归加进 `tests/test_marker_span_v224.py`。

## 2.2.4 — 2026-11-05

修一个会误导读者的排版细节：**证明的 qed 方块停在第一行**。

- **框与证明改成「跨段」，qed 落在真正的结尾**：旧实现一次只读标记行那一行，
  遇到空行或 `$$` 就收尾 —— 定理陈述里的块级公式被甩到框外，`[证明]` 的 qed
  方块停在「Proof. —— 直接用定义，把积分区间拆开：」那一行末尾，读者会以为
  证明到这儿就结束了（实测讲义截图报的就是这个）。现在 `[定义]` / `[定理]` /
  `[例]` / `[证明]` 从标记行一直收到下一个标记、标题或整行粗体的伪标题，
  块内的空行是段落分隔，`$$…$$`、列表、表格都留在装置里；`[直觉]` / `[练习]` /
  `[边注]` / `[强调]` 仍只吃标记行那一句。阅读版（`handout.py`）与填空笔记
  （`study_notes.py`）两条链路同一套口径。
- **`<label>` 三种位置都认**：标记行末尾、独占一行、最后一段末尾。跨段之后
  回指编号不会悬空，`_collect_refs` 与渲染共用同一个收集器。
- **四段式例题自动断段**：`题目 / 切入点 / 关键步骤 / 易错点` 紧跟句末标点
  （`。！？；`）时在标签前断段（`study_notes.split_review_labels()`，两条链路共用）。
  模型常把这四段写进同一个 `[例]` 行，不断段的话框里就是一大坨，读起来很费力；
  现在一条一行，正文一个字都不改。
- **节标题上方留白加大**：二级标题（绿色小节标题）`above` 12pt → **22pt**，
  一级标题 20pt → **24pt**（保持章 > 节的层次）。只改上方，行距与段距不动；
  阅读版 `handout_prelude.typ` 与填空版 vendored `src/lib.typ` 同步，
  数值仍以 `typography-spec.md` 的 `typography-params` 为准。
- **块内段落计入「方框:正文」分母**：内容搬进装置后分母不能凭空变小，否则
  比例检查会把正常讲义误判成「框框滥用」。
- **自测题：题干进琥珀框，答案排在框外**：`**1.** 题干` + `<details><summary>答案</summary>…`
  现在排成 `#selftest`（与「例」同款的棕色方框，标签「自测题 *n*」）与 `#answer`
  （框外、淡灰左线 + 「答案」标签），题目与答案之间有一道清楚的边界；手写的
  `**1.**` 编号交给标签，`<summary>` 的文字当答案标签。填空链路顺带修掉了
  `<details>` / `<summary>` 被转义后印成字面量的问题。
- **规范与 Skill**：`format-spec.md` 新增 §2.4「标记块到哪里结束（跨段规则）」与
  §2.5「自测题」；两个 Skill 与 README 同步口径；`tests/test_marker_span_v224.py`
  22 条 + `tests/test_selftest_v224.py` 9 条回归，含像素 + `pdftotext -bbox` 的
  qed 几何校验（方块必须落在证明最后一行；缺 poppler / Pillow 时跳过）。
- **市场条目描述收成一行的三句**（`market-submission/*.yml`）：按市场实际分布
  （en 中位数 212 / p90 445，zh 中位数 84 / p90 178）从 1226 / 561 字符压到
  326 / 165，只留「做什么 / 权限边界 / 来源」。`8eoyw` 参考实现、scholia 的作者
  与 Typst Universe 链接仍由 `ATTRIBUTION.md` / `README.md` 常设致谢承担；
  同时删掉会被站点当字面量印出的 `**`，以及「离线也能出 PDF」这类经不起对照
  `zju_lecture/deps.py` 的夸大（Typst 二进制是缺失时联网下载的）。
  `tests/test_docs_split.py` 增加长度与「纯文本」闸门，挡住再长回去。

## 2.2.3 — 2026-11-04

按又一次真实上课（`session-5415d8a5`，sub_id 1990907）里「工具没错、但 Agent 得替它
擦屁股」的地方收口。回归钉在 `tests/test_session_5415d8a5.py`。

- **`\qquad` / `\quad` 排成真间距**：以前映射成两个空格，Typst 会把空格折叠掉，
  四条麦克斯韦方程挤成 `0∇×H` 这种像乘法的东西；Agent 只好自己写
  `.tmp_split_display.py` 把 28 个公式块拆开、再重排两份 PDF。现在
  `\qquad` → `wide`（2em）、`\quad` → `quad`（1em）、`\,` → `thin`、`\;` → `med`，
  并保持转换幂等。
- **行内 `$1/r$` 不再顶高行距**：行内数学把 `/` 排成平排的 `slash`
  （`1 slash r`），独占一行的 `$$…$$` 仍排上下分式。此前 Agent 手改 4 处成 `r^{-1}`。
- **含公式的行不再拥挤**：Typst 的行内数学盒子高度是固定值（11pt 下 ≈0.68em，
  `measure($frac(1,2)$)` 与 `measure($x$)` 都是 7.51pt），分式的分子/分母、根式、
  大算子的上下限会溢出盒子、压到邻行（实测重叠 1–4pt），`par.leading` 管不到。
  现在两处显式留白：模板的 `#show math.equation.where(block: false)` 给每个行内
  公式补上 `0.12em` / 下 `0.10em`；`pad_inline_math()` 再给分式/根式/矩阵/大算子
  包一层 `#box(inset: (bottom: 0.30em))`。同一份讲义实测：行间 < 2pt 的行对
  37 → 15，最差一处 −3.74pt（重叠）→ +1.19pt，纯文字行的行距一点没动。
  数值进 `typography-spec.md` §3.2，两条链路由 `tests/test_typography_unified.py` 绑定。
- **引用块不再印出字面量 `>`**：Typst 没有 `>` 引用语法，旧实现把 `>` 原样写进
  PDF，还把抬头三个字段粘成「时长：约 01:40:16 上课时间：未提供…」。现在两条链路
  都渲染成左侧细线 + 灰色小字块，`**字段**：` 之间自动换行（`#quoted[…]`）。
- **`bare_imaginary_unit` 不再误报电流**：只有出现复数语境（`i^2`、`e^{iθ}`、
  `\pm i`、复数 / 虚部 / 相量等用语）时才报；LC 回路里的 `i = -q_0ω_0 sin(…)`
  不再逼 Agent 把物理量改成 `\mathrm{i}`。
- **方框预算按最小小节统计**：`## 二、分章详解` 下挂 7 个 `### 2.x` 时逐 `2.x` 计数，
  不再把整章 9 个框算成「一节超预算」（Agent 为此纠结过一大段）。
- **新增 `zju_build_study_notes(mode="patch")`**：`edits=[{old, new}, …]` 一次写回
  十几处挖空 / 标记，逐条报告命中与未命中；`old` 默认要求唯一命中（重复时加
  `"all": true`）。此前 35 步里有 12 步是一条一条改底稿。
- 顺带收紧投影抓取的失败文案：`ZJU_COOKIE_FILE` 的建议不再在 5 行报错里出现两次。
- **列表序号之间留出呼吸**：`-` 与 `1.` 的相邻条目间距 0.3em → **0.7em**
  （两条链路同一组参数，`list.spacing` / `list.indent` 进 `typography-spec.md`
  的机器可读块）；原来相邻条目几乎粘在一起。版式规范与实现由
  `tests/test_typography_unified.py` 绑定。

## 2.2.2 — 2026-11-04

修一次真实上课（sub_id 1990907，大学物理·麦克斯韦方程组）里暴露的**多余手工操作**：
PDF 因两个没映射的 LaTeX 符号直接跳过，Agent 手改 Markdown；填空底稿的每节空占位
要删改近 20 次；`---` 被排成孤立「–」，Agent 写通配脚本清理时误伤旧讲义。
回归钉在 `tests/test_session_7402719b.py`。

- **补上 `\perp` / `\leftrightarrow` 等关系符号**：`zju_write_note` 首次排版返回
  `PDF 跳过: error: unknown variable: leftrightarrow`，`note_lint` 还对 `\perp`
  报「没有 Typst 对应写法」。现在两者都映射为 `⊥` / `↔`，并补齐常用双向箭头、
  `\parallel`、`\nparallel`、`\hookrightarrow`、`\doteq` 等；`latex_unmapped`
  自然消失。
- **斜杠分式归一化**：`\partial D/\partial t`、`\mathrm{d}i/\mathrm{d}t`、
  `\sqrt{\mu_0/\varepsilon_0}` 在渲染层转成 `\frac{…}{…}`，不再需要 Agent
  写脚本逐条替换；只处理明确的微分/根式，不动普通 `a/b`。
- **修 `bare_imaginary_unit` 误报**：`$L\frac{\mathrm{d}i}{\mathrm{d}t}$` 里的
  `i` 是电流，不是虚数单位；负向后行断言把 `}` 也排除，不再逼 Agent 把电流改成
  `\mathrm{i}`（那会把物理量改错）。
- **填空底稿不再逐节塞空占位**：`build_draft` 以前在每节插
  `[直觉]（用一句人话解释…）` / `[练习]（留给读者自己重做的一题）` /
  `[边注]（一个主动回忆问题）`，实地会话为此花了近 20 次编辑。现在只保留原文，
  文件头留一条 HTML 注释说明可选装置；加不加、加在哪儿由内容判断。
- **`---` 水平分隔线不再变成孤立「–」**：`render_typst` 现在把独占一行的
  `---` 映射成 `#divider`（与 `[分隔]` 同款细线）。此前 Agent 只能写
  `知识总结*.md` 通配脚本删分隔线，误伤了另外两份旧讲义；Skill 也补了
  「不要用通配批量改讲义」。
- **小节标题后的间距加大**：一级标题下 8pt → 12pt，二级标题下 0.5em → 0.85em，
  三级标题下 0.4/0.5em → 0.65em；两条 PDF 链路同步（改 vendored scholia 补丁）。
  规范机器可读块新增 `heading.h{1,2,3}.above/below`，测试逐项比对。
- **新增主界面左栏入口**：`lib/client.js` 增加 `sidebar.panellist` 一行「智云讲义」
  （`id: zju-lecture`，order 30，排在「插件」「自动化任务」之后），点开在**主区域**
  渲染与「设置 → 浙大智云课堂讲义」完全相同的页面——同一个 `PipelineSettings`
  控制器、同一份配置，设置弹窗里的那一栏保留。折叠态只显示 `currentColor` 的 SVG
  图标，页首按 `--dsh-frame-top-clearance` 让出窗口标题栏。回归钉在
  `tests/test_sidebar_entry_v222.py` 与 `tests/client_settings_smoke.mjs`。
- 版本 2.2.1 → 2.2.2（六处对齐，两个 Skill 清单重新生成）。**尚未发布**。

## 2.2.1 — 2026-11-04

修一次真实上课（sub_id 1990049，89 步）暴露的**自相矛盾**：工具和文档各说各话，
Agent 只好拿 50 步去猜；同批把方框标签的字体层次找回来。回归钉在
`tests/test_session_d0cfd0ac.py` 与 `tests/test_box_style_v221.py`。

- **底稿契约统一成「纯 Markdown + LaTeX」**：`zju_build_study_notes(mode=draft)`
  以前会把公式改写成 Typst（`frac(…)` / `cal(…)`）、把表格写成 `#table(…)`、
  把有序列表写成 `+`，而工具自己的提示、`SKILL.md`、`format-spec.md` 都说
  「公式写 LaTeX，工具会转」——模型照着文档补 LaTeX，第二次转换就把已经转好的
  `frac` / `cal` 逐字母拆成 `f r a c` / `c a l`，编译报 `unknown variable`。
  现在 `draft` 只搬运结构，**转换只在 `compile` 做一次**。
- **LaTeX → Typst 转换变成幂等的**：`_plain_word` 认识转换器自己会产出的名字
  （`frac` / `cal` / `sum` / `quad` / `cdots`…），引号串（`"Res"`、`"d"`）原样搬运。
  以前 `latex_to_typst(latex_to_typst(x)) ≠ latex_to_typst(x)`，一次误转就毁一份公式。
- **补齐 Markdown 结构映射**：`render_typst` 新增 GFM 表格（→ `#table(…)`）、
  无序/有序列表（→ Typst 列表）、`**粗体**`（→ `*粗体*`）三个分支。
  此前表格只在 `draft` 转、`render_typst` 不认，底稿里的 `#table(` 会被当正文
  转义成 `\[…\]`；`**` 会触发 `warning: no text within stars`，加粗失效。
- **行内代码不再转义**：`` `[00:20]` `` 曾变成 `` `\[00:20\]` `` 印在 PDF 里；
  反引号在 Typst 是 raw，内容原样输出才对。
- **补上掉的数学符号**：`\triangleq`（Typst 没有这个符号，曾让整份 PDF 失败）→ `≙`；
  `\not\to` / `\not=` 等前缀否定 → `↛` / `≠`（以前直接印成 "not →"）。
- **「检查通过」和「PDF 能编译」不再打架**：`note_lint` 新增 `latex_unmapped` 规则，
  命令表取自转换器自己的 `supported_latex_commands()`，行内与块级公式都查。
  `zju_write_note` 返回 `PDF 跳过` 时多给一句可执行下一步（改完再
  `zju_check_note(pdf=true)` 重排一次）。
- **填空笔记 PDF 落在底稿同目录**：以前只在 `*-typst/out.pdf`，Agent 每次得手动
  `cp` 才交得出来；现在同时写 `<底稿名去掉 -填空底稿>.pdf`，工具直接返回该路径。
- **方框标签换成无衬线（两条链路一起）**：`Definition 1.1` / `Theorem 2.1` /
  `Example` / `Your turn.` 原先用的是 `heading`（衬线 + 楷体），和正文糊在一起，
  看不出「这是一个框」。现在标签走 `sans`：`Noto Sans` → `Liberation Sans` →
  `DejaVu Sans`，中文仍回 `Notes Kai SC`。上游用 Optima（也是无衬线），这条是
  把被字体补丁改丢的层次找回来。**没有**把 `Noto Sans SC` 放进栈里：本机那份是
  可变字体，Typst 只取到 Thin（`pdffonts` 里是 `NotoSansSC-Thin`），中文会发灰。
- **「伪方框」检查**：`note_lint` 新增 `pseudo_box`。把例题/定理/证明写成
  `#### 例 1：…` 或 `**证明（…）**` 时，PDF 里只会是小标题/粗体 —— 实测一份
  3.5 万字的讲义因此整页没有一个框。现在检查器会点名，并给出 `[例] 标题 —— 正文`
  的改法；讲义 Skill 与系统提示同步补了对照表。
- **填空笔记不再覆盖阅读版 PDF**：`<讲义名>-填空底稿.md` 编译出的 PDF 曾落到
  `<讲义名>.pdf`，正好把刚排好的阅读版覆盖掉；现在自动底稿输出
  `<讲义名>-填空.pdf`，手写底稿保持同名。
- 系统提示与 `SKILL.md` / `format-spec.md` / `docs/technical.md` 同步口径：
  底稿只补占位符、不要重写全文，公式保持 LaTeX。
- 版本 2.2.0 → 2.2.1（六处对齐，两个 Skill 清单重新生成）。

## 2.2.0 — 2026-11-03

- **两条 PDF 链路统一到同一套排版**：阅读版讲义与填空笔记现在共用 30pt 封面标题 /
  10pt kicker / 13pt 副标题 / 11pt 作者 / 9pt 日期、15 / 12.5 / 11.5pt 三级标题、
  2.4 / 3.9 / 2.0 / 2.3cm 版心、2.6cm 边注栏（与版心间距 0.7cm）、
  0.82em / 0.5em 边注；直觉块首行**不缩进**（按参考图口径），正文段首仍空两格。
  实测两份 PDF 的正文左/右边界与边注左边界一致（误差 ≤ 2pt）。
- **随包 `Notes Kai SC`（OFL 楷体）**：`zju_lecture/fonts/NotesKaiSC-Subset.ttf`
  是 LXGW WenKai（霞鹜文楷 v1.530）的 GB2312 子集，约 3.6MB；上游有 Reserved
  Font Name，因此**改名**。两条链路的中文首选都是它，复现参考图的楷体观感，
  且不再把 Windows 的 KaiTi 子集嵌进 PDF。`OFL-Kai.txt` 与 `FONT-NOTICE.md`
  随包分发；`tools/build_font_subset.py` 现在可一次生成 Serif / Kai 两个子集。
- **vendored scholia 打补丁**：`src/fonts.typ` 的 `default-fonts` 改为可再分发栈
  （移除 Optima / Avenir Next / Menlo / Songti SC），`src/lib.typ` 统一二级/三级
  标题字号与边注段距。补丁在 `tools/vendor_typst_packages.py` 里可重放，
  `VENDORED.md` 如实记录；`--check` 会验证补丁已生效。
- **规范去重**：重写 `skills/scholia-notes/references/typography-spec.md` 为
  唯一排版真相源（含机器可读的 `typography-params` 块）；`format-spec.md` /
  `style.md` / `api.md` / `docs/technical.md` / `SKILL.md` 的数值改为指向它。
  新增 `tests/test_typography_unified.py`（规范 ↔ 实现 ↔ 渲染几何 ↔ `pdffonts`），
  `test_palette_sync.py` / `test_deps_v210.py` 扩展到 Kai 字体与 vendored 字体表。
- **文档口径**：填空式学习笔记统一表述为「基于 Typst scholia 模板排版的填空式学习笔记；
  配色与段落规范由本项目定义，见 scholia-notes 规范」。README / ATTRIBUTION /
  THIRD_PARTY_NOTICES / docs/technical / SKILL / typography-spec 已同步。
- 版本 2.1.1 → 2.2.0（六处对齐，两个 Skill 清单重新生成）。

## 2.1.1 — 2026-11-03

- **修复「设置全开还是只有字幕」的根因**：dsh 把 `.volatile()` 的 `Config` 字段投影成
  实时引用（`{ get() }`），插件却直接拿它和 `true` 比较——引用永远不等于 `true`，于是
  `enableSlides` / `enableStudyNotes` / `enableLoginTools` / `embedSlideImages` 无论用户
  怎么保存都读成 `false`（`renderPdf` 因为写的是 `!== false` 反而一直是开）。新增
  `readSetting()` 统一解包引用，`featureFlags()`、`timeoutMs`、`python`、`registerSkill`
  都走它；`tests/plugin_apply_smoke.mjs` 增加「ref 形状」用例，防止再退回。
- **讲义默认按「复习版」写**：系统提示与 Skill 不再把增强内容写成「可选/需要时」——
  例题按「题目 → 切入点 → 关键步骤 → 易错点」整理（本节没有就写「本节无例题」，
  不编题），文末给 3–5 道自测题（答案折叠）与 5–10 条考点预测。
- **开关打开即默认执行**：`enableSlides` → 写讲义前抓一次投影并挑 3–8 页；
  `enableStudyNotes` → 写完讲义再出填空版。MCP 的 `initialize.instructions` 同步。
- **设置页口径改成真话**：保存只对新建会话生效，当前会话的工具集在开始时已固定；
  工具数标签从「本次会话注册」改为「当前配置注册」。
- 版本 2.1.0 → 2.1.1（六处对齐，两个 Skill 清单重新生成）。

## 2.1.0 — 2026-11-03

- **PDF 装完即用（Typst 自举）**：新增 `zju_lecture/deps.py`，把「本机没装 Typst」从静默的
  `PDF 跳过` 变成一次可解释的准备：`ZJU_TYPST_BIN` → 插件缓存 → `PATH` → 常见目录；版本低于
  0.13.0 提示升级；缺失时按平台从 **GitHub 官方 Release** 下载，只信任
  `zju_lecture/typst_assets.json` 里钉死的 SHA256（6 个平台，`tools/pin_typst_assets.py` 生成），
  解压后再用 `typst --version` 复核。下载失败写 6 小时冷却标记，避免每份讲义都卡一次超时。
  开关 `typstAutoInstall` / `ZJU_TYPST_AUTO_INSTALL`（默认开），镜像前缀 `ZJU_TYPST_MIRROR`。
- **随包中文字体**：`zju_lecture/fonts/NotesSerifSC-Subset.ttf` —— Noto Serif SC 的
  GB2312 + 常用符号子集（约 7.5k 字，5.7 MB，保留 `wght` 变量轴），**改名为 `Notes Serif SC`**
  以免与本机完整字体重名。两条 PDF 链路都把它排在中文首位，干净 Windows 上标题也有真正的粗体。
  随附 `OFL.txt` 与 `FONT-NOTICE.md`（OFL 1.1 要求随字体分发）。`tools/build_font_subset.py`
  从 Google Fonts 固定 URL 取源字体并按 SHA256 校验，产物可复现。
- **Typst 包 vendor（离线编译）**：`zju_lecture/typst-packages/` 收录 scholia / frame-it /
  marginalia / theoretic / showybox / noteworthy 六个包（约 257 KB），编译统一带
  `--package-path` 与工作区内的 `--package-cache-path`，填空笔记首次编译不再访问 Typst 包注册表。
  **逐包保留 `LICENSE` / `UNLICENSE` 与 `typst.toml`**，只删除 README 与模板示例；
  `tools/vendor_typst_packages.py` 可重建，`VENDORED.md` 记录版本与许可。
- **新工具 `zju_doctor`**（第 10 个，始终常驻）：报告 Python / Typst（版本 / 路径 / 来源）/
  随包字体 / Typst 包 / 缓存 / 自动安装开关；`install=true` 立即下载安装。默认工具数 5 → 6，
  全开 9 → 10。
- **设置页新增「环境与依赖」**：`typstAutoInstall` 开关 + 依赖说明；PDF 提示不再说「需要本机装 Typst」。
- **打包**：npm `files`、`pyproject` package-data、`tools/build_plugin.py` 都纳入字体、vendored 包与
  资产清单；MCode 包的收集逻辑从「只收 `.py` / `.pem`」改为递归收 `.typ` / `.toml` / `.ttf` /
  `LICENSE` 等，修掉此前 MCode 包缺 `prelude.typ` 的隐患。
- **文档口径修正（合规）**：`README` / `ATTRIBUTION` / `docs/technical.md` /
  `THIRD_PARTY_NOTICES.md` / 市场条目中「编译期拉取、未随仓库分发、No upstream code is copied」
  等表述改为「已 vendor 并附许可」；补「非官方工具，与浙大无隶属关系」声明；补 Typst 二进制的
  Apache-2.0 边界（不随包分发，若将来转分发需补 LICENSE / NOTICE 与内嵌字体许可）。
- **测试**：新增 `tests/test_deps_v210.py`（清单 / 校验和 / 平台映射 / 恶意归档 / 字体改名 /
  vendor 许可 / doctor / 离线编译 / 打包清单）。
- **npm 发布**：`package.json` 增 `prepublishOnly`（全量测试 + 隐私扫描，测试红了发不出去）；
  README 把 npm 安装写成首选、GitHub 仓库安装降为备选；`docs/technical.md` §10 补齐发布顺序
  （pack → 扫 tarball → publish --dry-run → publish）；README 行数闸门从 260 行放宽到 300 行。

## 2.0.2 — 2026-11-03

- **阅读版讲义 PDF 按参考图重做**：一级标题是「灰蓝编号 + 蓝色标题 + 细横线」；
  直觉 / 定义 / 定理 / 例 / 练习用淡彩底 + 左侧竖线的方框；证明以斜体 `Proof.` + 行末 qed 结束；
  边注进右侧留白栏；表格改三线表；封面、目录、代码块重排。配色与 scholia 填空笔记同一套
  （蓝 = 结论、青绿 = 定义、琥珀 = 例子 / 练习、灰 = 次要）。
- **版心**：左 2.4cm / 右 3.9cm，右侧 2.6cm 是边注栏；封面与目录不占页码，正文第一页从 1 起。
- **标记语法**：普通讲义也能用 `[直觉]`、`[定理] 标题 —— 正文`、`[定义]`、`[例]`、
  `[证明]`、`[练习]`（3 行书写位）、`[边注]` / `[边注!]`、`[强调]` / `[易错]` / `[弱注]`、
  `[分隔]`、`____`、`[缺口: …]`、`<def:x>` + `@def:x` 回指。语义、预算与数学写法由
  `format-spec.md` 统一规定，填空笔记与阅读版讲义两条链路共用。
- **数学环境**：`pmatrix` / `bmatrix` / `cases` / `aligned` 会机械转成 Typst 的
  `mat` / `cases` / 对齐换行；多字母标识符（`AC`、`e^{-st}`、`BVP`）不再让 PDF 编译失败。
- **配色单一来源**：浅色 soft-palette 只定义在 `zju_lecture/prelude.typ`；
  `handout_prelude.typ` 与 `handout._PALETTE` 是它的生成副本，
  `python tools/sync_palette.py` 同步、`--check` 在测试里守住三处一致。
- **字体默认可分发**：讲义模板首选 STIX Two（SIL OFL），退到 Typst 内嵌的 Libertinus /
  New Computer Modern / DejaVu；中文优先 Noto Serif SC / Source Han Serif SC。
  商业专有字体（Optima / Avenir Next / Menlo / Songti SC）降为注释里的「本机原味」选项。
- **文档重构**：README 只保留安装与使用，技术细节移到 `docs/technical.md`，版本历史移到本文件。
  插件市场条目补齐上游 PDF 模板 `@preview/scholia` 的署名与「未拷贝源码 / 未获背书」说明。
- **测试**：`tests/test_handout_v202.py` 覆盖标题编号剥离、全部标记装置、回指、方框预算、
  模板自包含、数学环境与真实编译；`tests/test_palette_sync.py` 覆盖配色一致与字体可再分发性。
- **行内代码不再被自动修复改写**（感谢 [@RTXwcz](https://github.com/RTXwcz) 提交
  [#2](https://github.com/chenqianyu486-sys/dsh-zju-lecture-note/pull/2)）：
  `_apply_outside_code` 改为按反引号 run 长度配对 —— 用两个或更多反引号包住的
  `\frac12` 保持原样（旧实现逐字符切换状态，双反引号跨度会被误改）；
  代码跨度保护下沉到 `_normalize_math` 内部，所有调用方一致。代理报错在未设置代理时
  点名 `HTTPS_PROXY` / `HTTP_PROXY`，不再输出 `（(未设置)）`。

## 2.0.1

- **自动 PDF 讲义**：`zju_write_note` 写入后自动把同一份 Markdown 排成同名 PDF
  （封面 / 目录 / 标题 / 正文 / 列表 / 表格 / 公式 / 代码 / 引用 / 图片），本地 Typst 完成，
  模型只多收到一行路径；PDF 失败不影响 Markdown。实现见 `zju_lecture/handout.py`，
  工程目录 `<工作区>/.zju-lecture/handout/`。
- **功能解耦**：新增 `enableStudyNotes` 与 `enableLoginTools` 两个 dsh 设置
  （MCP：`ZJU_ENABLE_STUDY_NOTES` / `ZJU_ENABLE_LOGIN_TOOLS`）。默认只注册 5 个核心工具；
  填空笔记、投影抓取、登录辅助各自独立，关掉时不注册工具、不加载对应代码、不追加 Skill 附录。
- **GUI 重做**：设置页按「核心 → 阅读 → 复习 → 投影 → 登录」分组，显示当前工具数、PDF 状态、
  模块依赖和一枚 `已保存` 反馈；新增 **省 Token / 复习模式 / 全功能** 三个一键预设。
- **省 token 的流程修正**：Skill 不再要求先 `zju_parse_url`、写后也不再强制重复
  `zju_check_note`；系统提示压缩，明确「同一节课字幕只抓一次」「写入 + 校验 + PDF 一次完成」；
  `zju_build_study_notes(draft)` 的返回从整页说明压到几行。工具描述整体缩短。
- **测试**：新增 `tests/test_handout_v201.py`（渲染 / 编译 / 自动 PDF / 开关矩阵），
  更新 `plugin_apply_smoke.mjs` 与工具数断言。

## 1.6.0

- 新增工具 `zju_build_study_notes`（第 9 个），把讲义变成 scholia 填空式学习笔记：
  - `mode=draft`：讲义 → 填空底稿（标题层级映射、标记位插入、LaTeX 数学 → Typst 数学）；
  - `mode=compile`：底稿 → `main.typ` + `prelude.typ` → `out.pdf` + 逐页 `page-N.png`，
    并报告编译错误、方框视觉预算与悬空回指。
- 随包新增第二个 Skill `scholia-notes`（**非官方第三方工作流说明**，MIT，独立授权）：
  淡彩极简配色、视觉预算、内容出处规则、字体与分发注意事项、逐条第三方归属。
  本 skill 与 `@preview/scholia` 包的作者无关，也未获其背书。
- 新增 `zju_lecture/study_notes.py` 与 `zju_lecture/prelude.typ`（唯一权威副本）；
  `tools/sync_skill_assets.py` 负责把 prelude 同步到 Skill 目录并校验一致。
- 工具数 8 → 9；`lib/tools.js` / `lib/tools.schema.json` / 两个 Skill 清单重新生成。

## 1.5.1

- **新增总开关**：dsh 插件设置 `enableSlides`（默认 `false`）与 MCP 环境变量
  `ZJU_ENABLE_SLIDES`。关闭时 `zju_fetch_slides` 不注册、不读登录态、不下载截图；
  字幕主链路完全不受影响。MCP 宿主未设置该变量时保持旧行为（开启），设 `0` 即关闭。
- **代码层解耦**：`zju_lecture/__init__.py` 用 PEP 562 懒加载 `download_slides` /
  `build_slides_pdf` / `SlideError`；`mcp_server.py` 只在进入 `zju_fetch_slides` 分支时才导入
  `zju_lecture.slides`。纯字幕进程的 `sys.modules` 里不会出现截图/PDF 模块。
- **协议层解耦**：`tools/list` 与 `initialize.instructions` 按开关动态输出；关闭时即使客户端
  直接调用 `zju_fetch_slides`，也会得到可执行的「投影抓取未启用 + 如何开启」错误。
- **Skill 拆分**：`SKILL.md` 只保留字幕主链路；投影下载与插图规范移到
  `skills/zju-lecture-summarizer/SLIDES.md`，dsh 插件仅在 `enableSlides=true` 时追加到内存 Skill。
- **两层次开关**：`enableSlides` 是总开关，`embedSlideImages` 是「截图是否入讲义」子开关；
  总开关关闭时子开关无效。
- **图形化设置**：新增浏览器半边 `lib/client.js`，通过 `settings.section` 在设置左侧导航注册
  独立的「浙大智云课堂讲义」一栏；`enableSlides` / `embedSlideImages` 标记为 Schemastery
  `.volatile()`，通过共享 `configForms` 服务读写并带 revision 校验。
- 新增 `tests/test_feature_decoupling_v151.py` 与 `tests/client_settings_smoke.mjs`。

## 1.5.0

- `zju_fetch_slides` 按真实接口修正：从 Cookie 父域 `.zju.edu.cn` 会话中解析 `_token` 并加
  `Authorization: Bearer`；按 `course_id` + `page/per_page` 分页并按截图 URL 去重；正确解包
  `content.pptimgurl`（以前把 JSON 字符串当文字输出）。
- 新增 `download` / `output_dir` / `dedup` 参数与 CLI `slides --download`：截图存到
  `ppt-assets/<sub_id>/images/`，用纯标准库合成 `PPT-<sub_id>.pdf`（JPEG `DCTDecode`、
  PNG `FlateDecode`），连续字节完全相同的截图折叠为一页。
- 明确「接口返回截图，不是文字层 / OCR」：Skill 不再暗示能读取幻灯片文字。
- 安全：截图只允许 `https://*.zju.edu.cn`；ZJU 的 `http://` 自动升级 HTTPS；Cookie 只发给
  ZJU 图片主机、不发送 Bearer；跨主机重定向剥离凭据；写盘限制在工作区，最多 2000 张、
  单张 ≤ 32 MiB。
- 新增 dsh 设置 `embedSlideImages`（默认 `false`）与 MCP 环境变量 `ZJU_EMBED_SLIDES=1`。
- 参考 [`8eoyw/zju-learning-cli`](https://github.com/8eoyw/zju-learning-cli)（MIT）的公开实现思路，
  未拷贝代码；其基于 numpy/Pillow 的近似笔画去重未移植。
- 完善致谢：补充 `PeiPei233/zju-learning-assistant`、`8eoyw/zju-learning-cli` 及其上游参考项目。
- dsh 单独把 `zju_fetch_slides` 的超时提高到 600s。
- 新增 `tests/test_slides_v150.py`。

## 1.4.2

- `@deepseek-ai/schemastery` 从 `dependencies` 改为 `peerDependencies`（`^3.18.1`），
  与插件市场的推荐写法、`dshmarket` 保持一致：profile 里不会出现第二份运行时，
  peer 由 pnpm 在 `dsh plugin add` 时自动装好；本地目录安装只需补这一颗依赖。
- 文档口径统一到 **8 个工具**：`zju_write_note` 在 1.4.1 加入后，`README.md`、`ATTRIBUTION.md`
  与 `lib/index.js` 的注释还写着 7。

## 1.4.1

针对 [实地运行反馈](docs/issue-1.4.0-实地运行反馈.md) 的 8 项问题（真实一节课 `sub_id=1988057` 跑下来）：

| # | 修复 |
| :-: | :--- |
| P1-1 | 相对路径按**会话工作区**解析（`ZJU_WORKSPACE` → `PWD` → 进程 cwd）；找不到时回显**已尝试的绝对路径**。 |
| P1-2 | `fix=true` 新增**块级 `$$` 前后补空行**修复器：区分开块/闭块（不往公式体里插空行）、跳过代码块、保留列表缩进。 |
| P2-1 | 检查报告**按 `code` 聚合**：`[错误] display_not_isolated × 59` + 有界行号列表 + 少量示例，新增 `max_samples`（默认 3）。 |
| P2-2 | PPT / 视频直链失败分支改为**单一结论 + 单一动作**（`reason` 枚举 `abe` / `locked` / `no_rows` …）。 |
| P2-3 | 新增 `zju_write_note`：文件名由 Agent 按「上课日期 + 本节内容」起名，缺省才回退 `知识总结-<sub_id>-<课程简称>.md`；**同名拒绝静默覆盖**。 |
| P3-1 | 备份改写到备份目录（`ZJU_BACKUP_DIR`，默认系统临时目录），不再污染 `git status`。 |
| P3-2 | Skill 清单新增 `contentHash`；插件启动告警打印两边的 sha256；新增防回归测试禁止「让用户提供 cookie」这类过期文案。 |
| P3-3 | 字幕返回 **`ASR 可靠度`**（噪声比 / 碎句比 / 平均句长 / 高频口头禅 + 处置建议），`chunked` / `json` 视图给 `quality` 对象。 |

## 1.4.0

针对 [issue #1](https://github.com/chenqianyu486-sys/dsh-zju-lecture-note/issues/1) 的 11 项审查：

| # | 修复 |
| :-: | :--- |
| 1 | `fix=true` 不再改写行内代码/围栏代码里的示例 |
| 2 | 回写前先备份，再原子替换；工具卡类型从 `read` 改为 `edit` |
| 3 | DOCX 按 token 流解析，恢复段落、制表符、`<w:br/>` 与 XML 实体 |
| 4 | `chunked` / `json` 遵守 `max_chars`，超限时给 `truncated` / `next_start_minute` |
| 5 | 切片时同时报告「课程总时长」和「本次区间」 |
| 6 | 检测 `app_bound_encrypted_key`（ABE），命中时直接引导 `ZJU_COOKIE_FILE` |
| 7 | Cookie 兜底复制带上 `-wal` / `-shm` 并回放 WAL |
| 8 | `config.json` 移出敏感名单；凭据词改整词匹配 |
| 9 | PDF 解析失败时汇总每种库的失败原因，并给出当前解释器的绝对路径 |
| 10 | `isError` 已能冒泡；超时仅在无其他在途调用时才回收 Python 子进程 |
| 11 | 系统提示段落声明适用范围，只对智云课堂相关任务生效 |

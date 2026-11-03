# 更新日志

版本号在 `package.json`、`pyproject.toml`、`mcp_server.SERVER_VERSION`、
`.minimax-plugin/plugin.json` 与两个 Skill manifest 六处对齐。

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

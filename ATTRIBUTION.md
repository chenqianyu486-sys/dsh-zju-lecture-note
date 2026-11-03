# Attribution

本插件（ZJU Lecture Agent Plugin / `zju-lecture`）改编自开源项目
[`nzw806/zju-lecture-summerizer-`](https://github.com/nzw806/zju-lecture-summerizer-)，
遵循其 MIT 许可证。原项目的版权声明与许可条款完整保留在仓库根目录的
[`LICENSE`](LICENSE) 中。

## 复用自上游的部分

| 文件 | 来源 | 说明 |
| :--- | :--- | :--- |
| `zju_lecture/cookies.py` | 上游 `browser_cookies.py` | Edge Cookie 数据库定位、内置纯 Python AES-128-CBC 解密（macOS Keychain + PBKDF2-SHA1(1003)）、Windows DPAPI 解密。移植时改进了错误分类、临时文件清理与 Windows 侧 v10/v20 前缀兼容。 |
| `zju_lecture/client.py` | 上游 `pipeline.py` 的抓取逻辑 | 智云课堂公开字幕接口 `courseapi/v3/web-socket/search-trans-result`、投影 PPT 接口 `pptnote/v1/schedule/search-ppt`、播放器配置接口 `courseapi/v2/play-template/get-config`。 |
| `zju_lecture/formatter.py` | 上游 `pipeline.py` 的格式化逻辑 | 按分钟聚合、按字符数分块、时间戳格式化。 |
| `zju_lecture/courseware.py` | 上游 `pipeline.py` 的课件提取逻辑 | PPTX / DOCX / TXT / MD / PDF 纯标准库文本提取。 |
| `skills/zju-lecture-summarizer/SKILL.md` | 上游 README 与总结提示词 | 五段式讲义模板（速览表 / 分章详解 / 公式清单 / 考试信息 / 考点预测）、降噪规则、LaTeX 公式规范。 |

## 本插件新增的部分

- 标准 MCP stdio 服务器（JSON-RPC 2.0）与 10 个工具定义（dsh 默认按开关注册 6 个）；
- `server.mjs` 启动器：运行时解析 Python 解释器，跨平台统一用 `node` 启动；
- Skill 化的工作流 SOP；
- 协议级回归测试、FIPS-197 AES 已知向量测试、Edge Cookie 失败原因分类；
- MiniMax Code（MCode）插件包形态（`.minimax-plugin/plugin.json` + `zju-lecture.mcp.json`）；
- DeepSeek Harness（dsh）原生插件形态（本仓库根目录的 `package.json` + `cordis.patch.yml` + `lib/`，
  npm 包名 `dsh-zju-lecture-note`，与 MCP 形态共用同一份 Python 核心）；
- 隐私加固：Cookie 不进工具参数/返回值、全输出 redaction、Edge 数据库只读优先与安全清理、
  TLS 校验不降级、同域重定向限制、本地文件敏感路径拒绝、`tools/privacy_scan.py` 发布闸门。
  设计说明见 [`SECURITY.md`](SECURITY.md)。

## 参考实现（未拷贝代码）

v1.5.0 的智云投影 PPT 管线与「讲义插图」开关参考了以下项目的公开实现思路，
代码按本仓库的纯标准库与安全边界重新实现，未拷贝其代码：

| 项目 | 许可 | 参考点 |
| :--- | :--- | :--- |
| [`8eoyw/zju-learning-cli`](https://github.com/8eoyw/zju-learning-cli) | MIT | 从会话 Cookie 的 PHP 序列化值中解析 `_token` 并作为 `Authorization: Bearer`；`search-ppt` 的 `course_id` + `page/per_page` 分页与按 URL 去重；截图合成 PDF；ZJU `http://` 升级 HTTPS；按堂次组织 PPT 输出的思路。 |
| [`PeiPei233/zju-learning-assistant`](https://github.com/PeiPei233/zju-learning-assistant) | MIT | 智云课堂 / 学在浙大 API 流程的原始来源；本插件与 `zju-learning-cli` 的共同上游，其桌面端实现是很多边界问题的第一手参考。 |
| [`eWloYW8/ZJU-course-material-download`](https://github.com/eWloYW8/ZJU-course-material-download) | MIT | 课件/附件下载思路的上游参考（经 `zju-learning-cli` 致谢链）。本插件目前未使用其下载端点。 |
| [`Kcalb35/Tronclass-pdf-downloaderforChrome`](https://github.com/Kcalb35/Tronclass-pdf-downloaderforChrome) / [`fish-can/TronClass-PDF-Downloader`](https://github.com/fish-can/TronClass-PDF-Downloader) | 见各自仓库 | 预览器转 PDF 思路的上游参考（经 `zju-learning-cli` 致谢链）。本插件目前未使用该端点。 |
| [`xzzd-pro/xzzd-pro`](https://github.com/xzzd-pro/xzzd-pro) | 见项目仓库 | 关闭下载时的端点处理思路（经 `zju-learning-cli` 致谢链）。本插件目前未使用。 |

本仓库只实现了**连续字节完全相同**的截图折叠；`zju-learning-cli` 基于 numpy/Pillow 的
“笔画是否仍存在于后续页面”近似去重没有移植——那会打破本插件零第三方依赖的约束。

## 特别感谢

- [`nzw806/zju-lecture-summerizer-`](https://github.com/nzw806/zju-lecture-summerizer-)：最初的抓取框架与讲义模板，本插件的起点。
- [`PeiPei233/zju-learning-assistant`](https://github.com/PeiPei233/zju-learning-assistant)：把智云课堂 API 流程完整跑通的桌面端实现。
- [`8eoyw/zju-learning-cli`](https://github.com/8eoyw/zju-learning-cli)：把 PPT 鉴权、分页与 PDF 合成写成可脚本化 CLI，直接启发了本插件 v1.5.0 的修复。
- [`Typst`](https://typst.app)（Apache-2.0）：阅读版讲义与填空笔记两条 PDF 链路的排版编译器。
- [`@preview/scholia`](https://typst.app/universe/package/scholia)（MIT © Eric Yang）：填空笔记的排版引擎；阅读版讲义模板在视觉上参考其浅色 notes 主题。详见下方 v1.6.0 / v2.0.1 两节。
- [`certifi`](https://github.com/certifi/python-certifi) 与 [Mozilla CA Certificate Program](https://www.mozilla.org/en-US/about/governance/policies/security-group/certs/)：随包 CA 信任库。
- 所有为本插件提交 issue、做实地运行反馈、审查代码与文档的同学：真实课堂里的复现步骤和原始输出，是这些修复能落地的原因。

> 上述参考项目的版权归各自作者所有；若后续需要拷贝其中任何代码，将按其 MIT 许可证保留版权声明与许可文本。

## v2.0.1 新增：讲义阅读版 PDF（`zju_lecture/handout.py`）

`zju_lecture/handout.py` 与 `zju_lecture/handout_prelude.typ` 是本项目原创的
Markdown → Typst 直排模板，**不 import 任何 Typst Universe 包**，也不拷贝上游模板代码。
它只依赖 Typst 可执行文件与系统字体；封面、目录、标题、表格、代码、引用等样式由本项目实现。
许可随本仓库 MIT。

> 讲义阅读版 PDF 与填空笔记 PDF 是两条不同的链路；后者才使用下面的
> `@preview/scholia`，且只在 `enableStudyNotes` 打开时注册。
>
> v2.0.2 起，阅读版 PDF 的配色与装置语义（蓝/青绿/琥珀、note / knot / proof / 边注）
> 与 scholia 保持一致，作为两条链路统一的视觉规范；实现仍是本项目自己的 Typst
> 模板（`handout_prelude.typ`），**未拷贝上游源码**。
>
> 这里的「参考 scholia」指**视觉与信息结构**：浅色 notes 主题的配色角色
> （`thm` / `def` / `eg` / `warn` / `muted`）、命题—证明—边注的装置语义、
> 右侧 Tufte 边注与三线表。模板代码由本项目独立编写，不 import 上游包，
> 也不复制其 `src/`；色值本身（`soft-palette`）是本项目自定义的（见文末「配色方面」）。

## v1.6.0 新增：填空式学习笔记链路（`skills/scholia-notes/`）

| 项目 | 许可 | 版权人 | 说明 |
| :--- | :--- | :--- | :--- |
| [`@preview/scholia`](https://typst.app/universe/package/scholia) | MIT | [Eric Yang](https://github.com/Eryc123Y)（杨星宇） | 填空式学习笔记的排版引擎（knot / note / 右边栏 / 封面）。**v2.1.0 起随本仓库分发（vendored）**：`zju_lecture/typst-packages/preview/scholia/0.1.0/`，保留 `LICENSE` 与 `typst.toml`，只删除 README 与模板示例。 |
| [`@preview/frame-it`](https://typst.app/universe/package/frame-it) | MIT | Marc Thieme | scholia 的 knot 底层（figure + 原生 label 交叉引用）。随仓库分发，保留 `LICENSE`。 |
| [`@preview/marginalia`](https://typst.app/universe/package/marginalia) | UNLICENSE | 公有领域 | scholia 的右边栏边注。随仓库分发，保留 `UNLICENSE`。 |
| [`@preview/theoretic`](https://typst.app/universe/package/theoretic) | UNLICENSE | 公有领域 | noteworthy 的定理底层；随仓库分发，保留 `UNLICENSE`。 |
| [`@preview/showybox`](https://typst.app/universe/package/showybox) | MIT | Pablo González Calderón | noteworthy 的方框底层；随仓库分发，保留 `LICENSE`。 |
| [`@preview/noteworthy`](https://typst.app/universe/package/noteworthy) | MIT | Tarun Kumar Jana | scholia 的证明/注记底层；随仓库分发，保留 `LICENSE`。 |
| [`loom-notes`](https://github.com/Polaris-Aeterna/loom-notes) | MIT | 北极甜虾（Polaris） | 上游 `scholia` 作者声明其实现是受该项目**设计启发**的独立重写，未复用其源码；本仓库亦未分发其代码。 |

> **v2.1.0 起，6 个 `@preview` 包已 vendor 进 `zju_lecture/typst-packages/`**，用于离线编译。
> MIT 的「保留版权声明与许可全文」义务由此触发，已逐包保留 `LICENSE`；Unlicense 包保留 `UNLICENSE`。
> 修改范围仅限**删除文档**（README / template / tests），代码、`typst.toml` 与许可文件逐字节保持上游原样。
> 逐包版本见 `zju_lecture/typst-packages/VENDORED.md`。

**随包中文字体**（v2.1.0）：

| 项目 | 许可 | 版权人 | 说明 |
| :--- | :--- | :--- | :--- |
| Noto Serif SC → `Notes Serif SC` | SIL OFL 1.1 | Copyright 2012 Google Inc.；字体内部 © 2017-2023 Adobe | GB2312 + 常用符号子集（约 7.5k 字），保留 `wght` 变量轴。已改名以避免与本机完整字体冲突；`zju_lecture/fonts/OFL.txt` 与 `FONT-NOTICE.md` 必须随包分发。 |

**Typst 二进制**（不随仓库分发）：

| 项目 | 许可 | 说明 |
| :--- | :--- | :--- |
| [Typst](https://typst.app) 0.15.1 | Apache-2.0 | 插件不含二进制；缺少时从官方 GitHub Release 下载到用户缓存目录，按 `zju_lecture/typst_assets.json` 的 SHA256 校验。若将来改为随包/镜像分发，必须补 Apache-2.0 的 `LICENSE` 与 `NOTICE`，并带上其内嵌字体（Libertinus / New Computer Modern / DejaVu）的 OFL 声明。 |

本插件与 `@preview/scholia` 的作者**没有隶属关系，也未获其背书**；
「scholia」一词仅用于指代所依赖的 Typst 包（指示性使用），不主张任何商标权利。

`skills/scholia-notes/` 目录里的一切（工作流 SOP、淡彩 palette 与五个助手、
`api` / `mapping` / `style` / `troubleshooting` 文档）是本项目原创，以 MIT 发布，
见该目录下的 [`LICENSE`](skills/scholia-notes/LICENSE) 与
[`THIRD_PARTY_NOTICES.md`](skills/scholia-notes/THIRD_PARTY_NOTICES.md)。

`skills/scholia-notes/references/prelude.typ` 是**生成副本**，唯一权威副本是
`zju_lecture/prelude.typ`（随 Python 包分发，编译时写进项目目录）；
`tools/sync_skill_assets.py` 同步两者，`tests/test_study_notes.py` 校验逐字节一致。

### 字体：影响产物的可再分发性

Typst 编译 PDF 时会内嵌并子集化用到的字体。上游 `scholia` 的 `default-fonts`
把 `Optima`、`Avenir Next`、`Menlo`、`Songti SC` 放在首选位 —— **商业专有字体**；
`STIX Two` 为 SIL OFL，`Libertinus Serif` / `New Computer Modern` / `DejaVu Sans Mono`
由 Typst 运行时内嵌。字体文件不随本仓库分发，但**会进入生成的 PDF**。

本仓库的处理：

- **阅读版讲义**（`handout_prelude.typ`，默认 PDF 链路）**默认就用可再分发的字体栈**：
  `STIX Two Text` → Typst 内嵌的 `Libertinus Serif`，标题同理，mono 用
  `DejaVu Sans Mono`，中文优先 `Noto Serif SC` / `Source Han Serif SC`（皆 OFL）。
  默认产物不内嵌任何商业字体，可以直接对外分享。想在本机还原上游观感，
  模板里留了一份注释掉的 local 字体栈 —— 那种 PDF 不要再分发。
- **填空笔记**走上游包：`fonts:` 覆盖能改 `body` / `math` / `heading` / `sans`，
  但进不去 `note` / `sidenote` / `label-it`（这三个直接读包内 `default-fonts`）。
  所以 `zju_build_study_notes` 的 PDF 里嵌了哪些字体，取决于本机装了什么；
  要彻底可控只能 vendor 上游包并改 `src/fonts.typ`（届时须保留上游 MIT 声明）。
  `skills/scholia-notes/SKILL.md` 与 `references/troubleshooting.md` 给出了
  「对外分发前换成 STIX Two」的覆盖写法与 `pdffonts` 核对方法。

配色方面：**浅色主题（`soft-palette`）是本项目自定义的**，色值由
`zju_lecture/prelude.typ` 定义、`tools/sync_palette.py` 同步到讲义模板与 Python 侧；
深色主题由上游 `scholia` 自带。配色不改变上述任何 MIT 归属。

## 第三方数据：随包 CA 证书库
| 文件 | 来源 | 许可 | 说明 |
| :--- | :--- | :--- | :--- |
| `zju_lecture/cacert.pem` | [`certifi`](https://github.com/certifi/python-certifi) 的 `cacert.pem`，其上游是 [Mozilla CA Certificate Program](https://www.mozilla.org/en-US/about/governance/policies/security-group/certs/) 根证书库 | Mozilla Public License 2.0 | 原样复制（仅在文件头追加来源注释），作为 `certifi` 缺失时的信任库兜底。dsh 自带的 Python 解释器不含 certifi，没有这份文件时在根证书不全的机器上会 `CERTIFICATE_VERIFY_FAILED`。刷新方式见 `tools/refresh_ca_bundle.py`。 |

> 该文件只包含**公开的根证书**，不含任何私钥、站点证书或个人信息；它不会关闭 TLS 校验，
> 只是把信任库从"用户碰巧装了什么"变成"随包可复现"。

## 声明

本项目仅供个人学习使用：抓取的是本人有权限访问的课程回放，频率极低。请遵守
浙江大学智云课堂的使用条款，不要用于批量抓取、传播课件或任何商业用途。
登录 Cookie 属于个人凭证，不要提交到任何仓库或发送给他人。

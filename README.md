# 浙大智云课堂讲义插件（ZJU Lecture Agent Plugin）

> 面向 **DeepSeek Harness（dsh）** 与任意 **MCP 宿主**：把浙大智云课堂（`classroom.zju.edu.cn`）的课程回放
> 变成一份可复习、结构化、**能正常渲染**的讲义。
> 语音字幕 + 课堂投影 PPT + 本地课件，交给宿主智能体做知识蒸馏。
> **字幕接口公开免登录**；核心只用 Python 标准库（PDF 课件另需可选的 `pypdf`）。
>
> **隐私优先**：登录 Cookie 只进入本地进程内存，工具不收、不回显、不落盘、不写日志；
> 本地文件工具拒绝凭据与浏览器数据。细则见 [`SECURITY.md`](SECURITY.md)。

本仓库既是插件的**能力核心**，也是 **dsh 原生插件包的发布源**：Python 核心、MCP 服务器、
讲义 Skill，以及 dsh 用的 `package.json` / `cordis.patch.yml` / `lib/` 都在这里。
npm 包名 `dsh-zju-lecture-note`；两种形态随包携带**同一份** Python 实现，
工具名、参数、返回值完全一致，不会各自漂移。

---

## 这是什么

上游项目 [`nzw806/zju-lecture-summerizer-`](https://github.com/nzw806/zju-lecture-summerizer-) 用
Python 脚本 + 本地网页 + 写死的 DeepSeek key 完成"链接 → 讲义"。本插件保留它的抓取内核，
把模型调度交给宿主智能体（DeepSeek Harness / MiniMax Code / Claude Code / Cursor …），
并把整套流程封装成标准 **MCP Server + Skill**：

| 维度 | 上游（CLI + 本地 Web） | 本插件（Agent 插件 / MCP） |
| :--- | :--- | :--- |
| 交互 | 固定单次生成网页，无法追问 | 原生 Tool / Skill，可多轮单点答疑、生成自测题 |
| 模型 | 脚本内硬编码 DeepSeek API | 宿主智能体直接感知材料，统一上下文与计费 |
| 生态 | 孤立工具 | dsh 原生插件 / 标准 MCP，可与 Git、知识库、文档插件协同 |
| 依赖 | 常驻后台 Web 服务 | 按需 stdio 进程，零 pip 依赖 |
| 隐私 | 需要把 Cookie 交给脚本 | Cookie 只在本地内存中解析；工具不回显、不落盘 |

复用与新增的具体边界见 [`ATTRIBUTION.md`](ATTRIBUTION.md)。

## 两种形态，一套内核

| 形态 | 载体 | 适合谁 |
| :--- | :--- | :--- |
| **dsh 原生插件** | 本仓库根目录的 npm 包（`package.json` + `cordis.patch.yml` + `lib/`），随包携带 Python 核心 | DeepSeek Harness 用户 |
| **标准 MCP + Skill** | `server.mjs` 拉起一个 stdio MCP Server，附带 `skills/` 里的讲义 SOP | 任意 MCP 宿主（MiniMax Code、Claude Code、Cursor、Cline…） |

无论从哪种形态安装，Agent 看到的都是下面这 8 个工具。

## 隐私与安全（先看）

- **Cookie 不是工具参数**：`zju_fetch_slides` / `zju_get_video_url` 不接受 cookie 参数，
  `zju_read_browser_cookie` 也没有参数；登录态只能由本地配置（`ZJU_COOKIE` / `ZJU_COOKIE_FILE`）
  或本机 Edge 提供，模型无法把它写进参数或从返回值里读出来。
- **Cookie 不回显**：`zju_read_browser_cookie` 只返回名称、数量、长度与来源类别；
  所有 stdout / stderr / 错误消息还会再经过一次 redactor，注册过的 Cookie 值统一替换为 `[REDACTED]`。
- **Cookie 不落盘**：读 Edge 时优先只读打开数据库；必须复制时用 0600 私有临时文件，读完覆写并删除。
  服务端缓存只存在于 Python 子进程内存，进程退出即消失。
- **TLS 不降级，也不靠运气**：证书校验永远不会被关闭。信任库按 `certifi` → **随包 `cacert.pem`** → 系统根证书
  三级回落——dsh 自带的 Python 解释器不含 certifi，这份随包 Mozilla 根证书快照让"能不能抓字幕"不再取决于
  用户碰巧 pip 装了什么。三级都不够时才失败，并把**原因 + 下一步**一起返回
  （当前信任库、加载了几张 CA、`HTTPS_PROXY` 是什么、该装 `certifi` 还是把域名加进 `NO_PROXY`），
  而不是丢一句 `<urlopen error ...>` 让人猜。
- **瞬时故障有重试**：建连与**正文读取**都在重试范围内（`IncompleteRead` / `SSLEOFError` / 超时 / 5xx，
  共 3 次、指数退避 + 抖动）；证书校验失败**不重试**——那需要修，不需要重跑。
- **跨域重定向被拒绝**：避免 `urllib` 在 302 时把 `Cookie` 头重发到第三方域。
- **本地文件有边界**：`zju_extract_courseware` / `zju_check_note` 只接受课件与讲义扩展名，
  并拒绝 `.env`、凭据、私钥、浏览器 Cookie/Login Data 等敏感文件与目录；凭据词按分隔符**整词匹配**
  （`client_secret.json` 仍拒绝，`secret sharing 第5章.md` 放行），通用文件名 `config.json` 不再误伤。
- **不写用户目录**：插件把随包 Skill 注册到 dsh 技能表，而不是复制进 `$DSH_HOME`；无遥测、无后台服务。
- **可机器验证**：`python tools/privacy_scan.py` 扫描工作区，`--history` 扫描 git 历史，
  `--tarball` 扫描 npm 发布产物。

完整威胁模型与已知边界见 [`SECURITY.md`](SECURITY.md)。

## 工具清单

| 工具 | 功能 | 鉴权 | 隐私处理 |
| :--- | :--- | :--- | :--- |
| `zju_parse_url` | 解析回放链接，取 `sub_id` / `course_id` / `tenant_code` | 公开 | 纯字符串解析 |
| `zju_fetch_transcript` | 抓整节课或指定时间段的语音字幕，支持按分钟/逐句/分块/JSON 四种视图与字符上限 | **公开免登录** | 无 Cookie |
| `zju_fetch_slides` | 抓取课堂投影 PPT **截图清单**；可选下载截图并合成 PDF（接口不返回文字层/OCR） | 需登录态（Cookie 需含 `_token`） | 不收/不回显 Cookie |
| `zju_extract_courseware` | 提取本地 PPTX / DOCX / TXT / MD / CSV / JSON / PDF 文本 | 本地文件 | 拒绝敏感路径 |
| `zju_check_note` | 检查讲义 Markdown 的公式规范与渲染（一键修复机械问题；报告按问题类型聚合） | 本地文件 | 只接受 `.md` / `.markdown` |
| `zju_write_note` | 写入讲义：文件名由 Agent 按「上课日期 + 本节内容」命名（如 `知识总结-2026-10-28-复变函数-保角映射.md`）、拒绝静默覆盖、写前修正 + 写后校验 | 本地文件 | 只写工作区内的 `.md` |
| `zju_get_video_url` | 解析回放 MP4 直链（供下载或 Whisper 重识别） | 需登录态（服务端本地解析） | 直链可能带签名，勿外传 |
| `zju_read_browser_cookie` | 读取本机 Edge 登录态并缓存到服务端内存 | 本机读取 | **只返回名称与长度** |

> **智云投影 PPT 是截图，不是文字**：`search-ppt` 返回的是投影画面截图（`pptimgurl`）。
> `zju_fetch_slides` 默认只给截图清单与页数；传 `download=true` 时会把截图下载到
> `<工作区>/ppt-assets/<sub_id>/images/`，并合成 `PPT-<sub_id>.pdf`（JPEG 直嵌、PNG 解码，
> 连续字节相同的截图折叠为一页）。只传纯 `sub_id` 时必须同时给 `course_id`；
> 鉴权使用 Cookie 父域 `.zju.edu.cn` 中的 `_token`（`Authorization: Bearer`）。

## 安装

### 1. DeepSeek Harness（dsh）

dsh 插件是 **pnpm 包**：`dsh plugin` 会把参数原样转给 profile 目录里的 pnpm，
所以来源写法与 pnpm 一致（npm 包名 / `github:` / `file:`）。

```bash
# 从 GitHub 仓库（就是本仓库）—— 当前可用的安装方式
dsh plugin --profile desktop add github:chenqianyu486-sys/dsh-zju-lecture-note

# 从 npm registry（包发布到 npm 之后才可用，包名 dsh-zju-lecture-note）
# dsh plugin --profile desktop add dsh-zju-lecture-note

# 从本地路径（开发 / 验证）
dsh plugin --profile desktop add file:/absolute/path/to/zju-lecture-agent-plugin
```

> **本包目前还没发布到 npm registry**（`dsh-zju-lecture-note` 在 npm 上查无此包），
> 请用上面的 `github:` 写法安装；等发布后再换回包名写法。

> `desktop` profile 由 DeepSeek Harness 桌面端持有，管理插件时请使用
> **DeepSeek Harness 自带的 dsh 命令**（`resources/runtime/cli/bin/dsh.cmd`），
> 而不是 npm 全局安装的 `dsh`；`web` / `headless` 等 profile 用哪个都可以。

**不要只把 GitHub 的 zip 解压出来让 dsh 加载。** 插件是 Node ESM 包，
`lib/index.js` 里的 `@deepseek-ai/*` 全部是 **`peerDependencies`**（与 `dshmarket` 一致），
由 pnpm 在 `dsh plugin add` 时装进 profile 的 `node_modules`（当前是 `@deepseek-ai/schemastery` 3.18.x）；
解压出来的目录本身没有 `node_modules`，启用时会报：

```text
Cannot find package '@deepseek-ai/schemastery' imported from ...\lib\index.js
```

若一定要用本地目录，先给它补一个能被解析的 schemastery（其余 `@deepseek-ai/dsh-*`
仍由 dsh 运行时提供），再让 dsh 加载：

```bash
cd /absolute/path/to/zju-lecture-agent-plugin
npm install --no-save --no-package-lock @deepseek-ai/schemastery@^3.18.1
dsh plugin --profile desktop add file:/absolute/path/to/zju-lecture-agent-plugin
```

`--no-save --no-package-lock` 让这次安装只落进目录的 `node_modules`，不改 `package.json`
（`@deepseek-ai/dsh-*` 是 dsh 提供的 peer，不要在这里重复安装）。

装完后在 dsh 里直接说：

> 帮我把这节课整理成讲义：https://classroom.zju.edu.cn/livingroom?course_id=58133&sub_id=123456

> **版本要求**：dsh 会按 `peerDependencies` 中的 `@deepseek-ai/dsh-*` 范围校验运行时版本；
> 本插件声明 `>=0.2.0-rc.2 <0.3.0-0`，不匹配时需要显式的版本豁免。
> **Python 探测顺序**：插件配置项 → 环境变量 `ZJU_PYTHON` → DeepSeek Harness 自带 Python → PATH 上的 `python3` / `python` / `py -3`。

**登录态（可选，仅投影 PPT / 视频直链需要）**：优先自动读本机 Edge；Edge 正在运行时数据库被锁，
且 Edge 127+ 若启用了应用绑定加密（ABE），退出 Edge 也无法在本地解密其 v20 Cookie，这时会直接
提示改用 `ZJU_COOKIE_FILE`。可在宿主配置里设置环境变量，**不要把 Cookie 粘贴到对话里**：

```bash
ZJU_COOKIE="name=value; name2=value2"        # 直接给 Cookie 头
ZJU_COOKIE_FILE="/absolute/path/cookie.txt"  # 或从本机文件读（一行，权限建议 600）
```

智云接口用 Cookie 会话中的 `_token` 做 `Authorization: Bearer` 鉴权；这个会话 Cookie 通常设在父域
`.zju.edu.cn`。插件从 Edge 读课堂域 Cookie 时会一并读取该父域 Cookie；手工配置 `ZJU_COOKIE` /
`ZJU_COOKIE_FILE` 时请确认里面包含它，否则 PPT 接口可能返回 401/403。

**工作区与备份位置（可选）**：

```bash
ZJU_WORKSPACE="/absolute/path/to/workspace"  # 相对路径（如 知识总结.md）按它解析；dsh 插件会自动传入
ZJU_BACKUP_DIR="/absolute/path/to/backups"   # zju_check_note / zju_write_note 的备份目录，默认系统临时目录
```

相对路径的解析顺序是：绝对路径 → `ZJU_WORKSPACE` → `PWD` → 服务进程自己的 cwd；都找不到时，
错误信息会列出**尝试过的绝对路径**，而不是只回一句"找不到"。

### 2. 任意 MCP 宿主（MiniMax Code / Claude Code / Cursor …）

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

`server.mjs` 会在运行时解析 Python 解释器（依次尝试 `ZJU_PYTHON` → `python3` / `python` / `py -3`，要求 3.9+），
因此配置里只需要一个在 PATH 上必然存在的 `node`。需要登录态时，把 `ZJU_COOKIE` 或
`ZJU_COOKIE_FILE` 放进该服务器的 `env`（部分宿主不支持 `env`，可用系统环境变量）。

Claude Code 一行接入：

```bash
claude mcp add zju-lecture node /绝对路径/dsh-zju-lecture-note/server.mjs
```

或把本仓库作为 Claude Code 插件目录使用（清单见
[`adapters/claude_code/plugin.json`](adapters/claude_code/plugin.json)）。

### 3. MiniMax Code（MCode）插件包

```bash
python tools/build_plugin.py --install          # 校验 + 安装到 ~/.minimax/plugins/zju-lecture
python tools/build_plugin.py --install --zip    # 同时产出 dist/zju-lecture-<version>.zip
```

安装后 MCode 的插件自动扫描会识别该包，启用后即可直接说：

> 帮我把这节课整理成讲义：https://classroom.zju.edu.cn/livingroom?course_id=58133&sub_id=123456

卸载：删除 `~/.minimax/plugins/zju-lecture` 目录。

### 4. 命令行

```bash
python -m zju_lecture.cli parse "https://classroom.zju.edu.cn/livingroom?course_id=58133&sub_id=123456"
python -m zju_lecture.cli fetch 123456 --format min -o 字幕.txt
python -m zju_lecture.cli fetch 123456 --start 20 --end 45
python -m zju_lecture.cli slides "https://classroom.zju.edu.cn/livingroom?course_id=58133&sub_id=123456" --download
python -m zju_lecture.cli courseware ./课件.pptx
python -m zju_lecture.cli cookie            # 默认只显示名称与长度
```

> CLI 的 `cookie` 子命令默认**不回显明文**；确实需要时加 `--reveal`（会进入终端历史）。
> `slides` 子命令优先用 `--cookie-file` / `ZJU_COOKIE`；`--cookie` 仍可用，但会出现在进程列表里。
> `slides --download` 输出到 `<工作区>/ppt-assets/<sub_id>/`（可用 `--out-dir` 改），并生成
> `PPT-<sub_id>.pdf`；`--no-dedup` 关闭连续重复截图折叠。

## 目录结构

```text
dsh-zju-lecture-note/
├── package.json                   # npm / dsh 插件包清单（包名 dsh-zju-lecture-note）
├── cordis.patch.yml               # dsh bundle patch（把插件插进 cordis）
├── lib/                           # dsh 插件实现（ESM）
│   ├── index.js                   # 插件入口：注册 8 个 dsh 工具 + 内存注册随包 Skill
│   ├── bridge.js                  # 拉起随包 Python 核心（JSON-RPC over stdio）
│   ├── tools.js                   # 生成物：dsh 工具定义
│   └── tools.schema.json          # 生成物：工具定义快照（供测试比对）
├── .minimax-plugin/plugin.json    # MiniMax Code（MCode）插件清单
├── zju-lecture.mcp.json           # MCP 服务器定义（stdio → node ./server.mjs）
├── server.mjs                     # 启动器：解析 Python 解释器并拉起 MCP 服务
├── mcp_server.py                  # MCP stdio 服务器（JSON-RPC 2.0，隐私边界在这里）
├── zju_lecture/                   # 核心库（纯标准库）
│   ├── client.py                  # 智云课堂 API 客户端（TLS 校验 + 同域重定向）
│   ├── cookies.py                 # Edge Cookie 读取与安全清理
│   ├── security.py                # Cookie 校验/redactor/本地文件边界
│   ├── courseware.py              # 课件文本提取（带路径校验）
│   ├── note_lint.py               # 讲义 Markdown 公式规范检查 / 自动修复
│   ├── formatter.py               # 时间戳 / 分钟聚合 / 分块
│   └── cli.py                     # 命令行入口
├── skills/zju-lecture-summarizer/SKILL.md         # 讲义生成 SOP（五段式模板 + 公式规范）
├── skills/zju-lecture-summarizer.manifest.json    # Skill 文件清单（sha256 审计）
├── SECURITY.md                    # 威胁模型 / Cookie 生命周期 / 已知边界
├── adapters/                      # 其它宿主的接入示例（不进入插件包）
├── tests/                         # 回归测试（含隐私扫描与插件形态测试）
├── tools/                         # 打包、schema 生成、隐私扫描、冒烟测试
├── icon.png / icon-dark.png       # 插件图标
├── LICENSE / ATTRIBUTION.md
└── README.md
```

## 隐私设计（工作原理）

### Cookie 从哪里来、到哪里去

1. 来源只有本地：内存缓存 → `ZJU_COOKIE` → `ZJU_COOKIE_FILE` → 本机 Edge；
2. 校验：拒绝换行（HTTP 头注入）、空 name、超长；不合法只返回原因，不回显内容；
3. 使用：只放进发往 `classroom.zju.edu.cn` 的请求头；跨域重定向拒绝；
4. 缓存：仅 Python 子进程内存；
5. 回显：没有；工具 schema 中没有 cookie / reveal / domain 参数；
6. 日志：所有输出经过 `SecretRedactor`；
7. 临时文件：只读打开优先；必须复制时连同 `-wal` / `-shm` 一起复制（刚登录的行可能还在 WAL 里），
   权限 0600，读完覆写并删除。

### 本地文件

`zju_extract_courseware` 和 `zju_check_note` 只接受指定扩展名，并拒绝敏感文件名/目录
（`.env*`、`*credential*`、`*.pem`、`Cookies`、`Login Data`、`.ssh`、`.dsh` 等）。
凭据类单词按分隔符整词匹配（`my-secret.txt` 拒绝、`secret sharing 第5章.md` 放行），
`config.json` 这类通用名不再被拒。符号链接会先解析真实路径再判定。
确有必要时可用 `ZJU_ALLOW_SENSITIVE_PATHS=1` 显式关闭保护。

### 数据会离开本机的部分

字幕与课件文本会作为工具结果进入宿主模型上下文，由你选择的模型提供方处理——这是使用大模型
整理讲义的固有代价。插件本身不收集、不额外上传、不写遥测。

### 讲义不进仓库

讲义是给自己复习用的**本机学习材料**，不是代码。开发者自己在这个仓库里跑插件时也一样，
默认就不会被提交：本仓库的 `.gitignore` 已经挡掉任意层级的 `知识总结*.md` 与 `/notes/`
（`git check-ignore -v 知识总结-2026-10-28-复变函数-保角映射.md` 可以自查）。

在你自己的项目仓库里用这个插件时，建议把这几行加进该仓库的 `.gitignore`：

```gitignore
# 智云课堂讲义（本机产物，不入库）
知识总结*.md
notes/
```

Agent 侧也写明了：**不要 `git add` / 提交讲义**，需要归档就把文件换个名字留在本地——
`zju_write_note` 的同名拒绝覆盖已经保证新讲义不会吃掉旧讲义。

## 讲义的公式规范

生成的讲义要**能渲染**，而不只是"公式写对了"。插件把这件事做成了两道闸门：

1. **规范写进 Skill**（`skills/zju-lecture-summarizer/SKILL.md` §4④）——行内 `$...$` / 独立 `$$...$$`、
   分式 `\frac{分子}{分母}`（分子分母都带花括号）、绝对值 `\lvert ... \rvert`（不写裸 `|`）、
   虚数单位 `\mathrm{i}`、中文不塞进 `\text{}`、`<details>` 写成多行。
2. **产出后自检**——`zju_check_note` 静态扫描讲义，捕获"表格列被裸竖线截断""行内公式没闭合"
   "块级公式没独立成行""`\frac` 缺花括号""单行 `<details>`"这类会让整篇散架的问题。

```bash
python tools/check_note.py 讲义.md            # 只检查
python tools/check_note.py --fix 讲义.md       # 自动修正机械问题（单行 $$ 块、$$ 前后缺空行、
                                              # \dfrac、\frac 补花括号、表格裸竖线、单行 <details>）
```

自动修复只做**语义无歧义**的改写，且只作用于围栏代码块与行内代码之外（讲义里"这样写是错的"示例
不会被改坏）；回写前会把原文件备份到备份目录（`ZJU_BACKUP_DIR`，默认系统临时目录下的
`zju-lecture-backups/`，报告里给出备份的绝对路径），再原子替换——备份不会再落在讲义同目录污染
`git status`。需要判断的（未闭合的 `$`、`\text{}` 里的中文、裸虚数单位）保持原样并继续报出来。

检查报告**按问题类型聚合**：59 处同类错误只打印一次 `[错误] display_not_isolated × 59`，附行号列表与
少量示例（`max_samples` 可调），长讲义不会再把工具返回刷成一屏。

## 开发与测试

```bash
python -m unittest discover -s tests -v     # 全部回归测试（含插件形态与隐私测试）
python tools/build_plugin.py --validate     # 按插件规范校验包结构
python tools/check_note.py 讲义.md           # 讲义渲染规范检查
python tools/privacy_scan.py                # 工作区隐私扫描（Cookie/密钥/个人路径/邮箱）
python tools/privacy_scan.py --history      # 连同 git 历史一起扫
python tools/export_schemas.py              # 改动 TOOLS 后重新生成适配器 schema
python tools/export_dsh_tools.py            # 改动 TOOLS 后重新生成 dsh 工具定义
python tools/build_skill_manifest.py        # 改动 Skill 后重新生成 sha256 清单
node tests/bridge_smoke.mjs                 # 端到端：拉起 Python 核心并调用一次工具
node tests/bridge_error_smoke.mjs           # 端到端：确认 MCP 的 isError 会冒泡成异常
node tests/bridge_workspace_smoke.mjs       # 端到端：相对路径按 session workspace 解析
python tools/refresh_ca_bundle.py --check   # 检查随包 CA 是否完整（≥50 张根证书）
python tools/smoke_test.py --sub-id <真实 sub_id>               # 对已安装包跑端到端冒烟（--dir 可指定包目录）
```

测试覆盖：URL 解析、时间戳格式化、分块时间区间回归、课件提取、工具 schema 健全性、
MCP 协议往返（`initialize` / `tools/list` / `tools/call` / 通知不响应）、
FIPS-197 AES-128 已知向量、Edge Cookie 失败原因分类、Cookie 主机精确匹配、Cookie 不回显与错误 redaction、
敏感本地文件拒绝、TLS 不降级与三级信任库回落、瞬时故障重试与证书失败不重试、`isError` 冒泡、
跨域重定向拒绝、讲义公式规范检查与自动修复、隐私扫描器自测、review 批次回归
（行内代码不被改写、修复前 `.bak` 备份、DOCX 段落保留、`chunked`/`json` 截断、切片时长、
Cookie WAL 回放、ABE 探测、PDF 报错带解释器路径、bridge 超时语义、系统提示适用范围）。

> 测试中的 `subprocess` / 管道 / 临时文件在受限沙箱里可能被拒绝；这是环境限制，不是插件缺陷。
> 在普通终端或给予足够的文件/进程权限后运行即可。

## 发布 dsh 插件包

本仓库根目录就是 npm 包（包名 `dsh-zju-lecture-note`），发布即发布这个仓库：

```bash
npm login                 # 首次发布前登录（交互式，需本人操作）
npm pack --dry-run        # 先看一眼会打进包里的文件清单
python tools/privacy_scan.py --tarball <生成的 .tgz>   # 发布前隐私闸门
npm publish               # 发布到 npm registry
```

`files` 字段是逐文件枚举的运行时清单（`lib/`、`mcp_server.py`、`zju_lecture/*.py`、`skills/`、
`SECURITY.md`……），**不要**改成整目录——否则 `__pycache__/*.pyc` 会混进包里
（`files` 的优先级高于 `.npmignore`）。

> dsh 按 `peerDependencies` 校验运行时版本。若升级 dsh 后插件被跳过，请检查
> `@deepseek-ai/dsh-*` 的 peer 范围，或按 dsh 提示使用 `dsh plugin allow-version` 做精确版本豁免。

## 1.5.0 智云投影 PPT 读取修复

- `zju_fetch_slides` 按真实接口修正：从 Cookie 父域 `.zju.edu.cn` 会话中解析 `_token` 并加
  `Authorization: Bearer`；按 `course_id` + `page/per_page` 分页并按截图 URL 去重；正确解包
  `content.pptimgurl`（以前把 JSON 字符串当文字输出）。
- 新增 `download` / `output_dir` / `dedup` 参数与 CLI `slides --download`：截图存到
  `ppt-assets/<sub_id>/images/`，用纯标准库合成 `PPT-<sub_id>.pdf`（JPEG `DCTDecode`、
  PNG `FlateDecode`），连续字节完全相同的截图折叠为一页。
- 明确「接口返回截图，不是文字层/OCR」：Skill 不再暗示能读取幻灯片文字；模型不能看图时只用字幕与本地课件，
  需要幻灯片原文时让用户提供原始 `.pptx` 走 `zju_extract_courseware`。
- 安全：截图只允许 `https://*.zju.edu.cn`；ZJU 的 `http://` 自动升级 HTTPS；Cookie 只发给 ZJU 图片主机、
  不发送 Bearer；跨主机重定向剥离凭据；写盘限制在工作区，最多 2000 张、单张 ≤32 MiB。
- 参考 [`8eoyw/zju-learning-cli`](https://github.com/8eoyw/zju-learning-cli) 的公开实现思路（MIT），
  详见 [`ATTRIBUTION.md`](ATTRIBUTION.md)；其基于 numpy/Pillow 的近似笔画去重未移植，保持零第三方依赖。
- dsh 单独把 `zju_fetch_slides` 的超时提高到 600s（下载整节课截图用），其他工具仍用配置值。

## 1.4.2 修正

- `@deepseek-ai/schemastery` 从 `dependencies` 改为 `peerDependencies`（`^3.18.1`），
  与插件市场的推荐写法、`dshmarket` 保持一致：profile 里不会出现第二份运行时，
  peer 由 pnpm 在 `dsh plugin add` 时自动装好；本地目录安装只需补这一颗依赖。
- 文档口径统一到 **8 个工具**：`zju_write_note` 在 1.4.1 加入后，`README.md`、`ATTRIBUTION.md`
  与 `lib/index.js` 的注释还写着 7。

## 1.4.1 修复了哪些问题

针对 [实地运行反馈](docs/issue-1.4.0-实地运行反馈.md) 的 8 项问题（真实一节课 `sub_id=1988057` 跑下来）：

| # | 修复 |
| :-: | :--- |
| P1-1 | 相对路径按**会话工作区**解析（`ZJU_WORKSPACE` → `PWD` → 进程 cwd）；找不到时回显**已尝试的绝对路径**。dsh 插件把 session workspace 传给 Python 子进程（同时作为子进程 cwd）。 |
| P1-2 | `fix=true` 新增**块级 `$$` 前后补空行**修复器：区分开块/闭块（不往公式体里插空行）、跳过代码块、保留列表缩进。 |
| P2-1 | 检查报告**按 `code` 聚合**：`[错误] display_not_isolated × 59` + 有界行号列表 + 少量示例，新增 `max_samples`（默认 3）。 |
| P2-2 | PPT / 视频直链失败分支改为**单一结论 + 单一动作**（`reason` 枚举 `abe` / `locked` / `no_rows` …），去掉错乱的编号与"退出 Edge 后重试；但 ABE 退出也无效"的自相矛盾。 |
| P2-3 | 新增 `zju_write_note`：文件名由 Agent 按「上课日期 + 本节内容」起名（`name` 参数，如 `知识总结-2026-10-28-复变函数-保角映射.md`），缺省才回退 `知识总结-<sub_id>-<课程简称>.md`；**同名拒绝静默覆盖**（返回 `exists`，要覆盖须显式 `overwrite=true`）。 |
| P3-1 | 备份改写到备份目录（`ZJU_BACKUP_DIR`，默认系统临时目录），报告给出绝对路径；不再污染 `git status`。 |
| P3-2 | Skill 清单新增 `contentHash`；插件启动告警打印两边的 sha256；Skill 增加「版本与副本核对」章节；新增防回归测试禁止"让用户提供 cookie"这类过期文案。 |
| P3-3 | 字幕返回 **`ASR 可靠度`**（噪声比 / 碎句比 / 平均句长 / 高频口头禅 + 处置建议），`chunked` / `json` 视图给 `quality` 对象；Skill 要求可靠度低时复算校核并在讲义顶部写明复核点。 |

## 1.4.0 修复了哪些问题

针对 [issue #1](https://github.com/chenqianyu486-sys/dsh-zju-lecture-note/issues/1) 的 11 项审查：

| # | 修复 |
| :-: | :--- |
| 1 | `fix=true` 不再改写行内代码/围栏代码里的示例（讲义里"这样写是错的"不会被改坏） |
| 2 | 回写前先备份 `<文件名>.bak`，再原子替换；工具卡类型从 `read` 改为 `edit`（1.4.1 起备份写到 `ZJU_BACKUP_DIR`，默认系统临时目录） |
| 3 | DOCX 按 token 流解析，恢复段落、制表符、`<w:br/>` 与 XML 实体 |
| 4 | `chunked` / `json` 遵守 `max_chars`，超限时给 `truncated` / `next_start_minute` |
| 5 | 切片时同时报告"课程总时长"和"本次区间"，不再把片段时长当整课 |
| 6 | 检测 `app_bound_encrypted_key`（ABE），命中时直接引导 `ZJU_COOKIE_FILE` |
| 7 | Cookie 兜底复制带上 `-wal` / `-shm` 并回放 WAL，不再误报"未登录" |
| 8 | `config.json` 移出敏感名单；凭据词改整词匹配，学术文件名不再误伤 |
| 9 | PDF 解析失败时汇总每种库的失败原因，并给出当前解释器的绝对路径 |
| 10 | `isError` 已能冒泡（1.3.3）；超时仅在无其他在途调用时才回收 Python 子进程 |
| 11 | 系统提示段落声明适用范围，只对智云课堂相关任务生效 |

## 已知限制

- **只解压 zip 就启用 → `Cannot find package '@deepseek-ai/schemastery'`**：
  它是 peer 依赖，由 pnpm 在 `dsh plugin add` 时装进 profile 的 `node_modules`，
  解压出来的目录里没有，所以直接加载会失败。
  用 `dsh plugin --profile desktop add github:chenqianyu486-sys/dsh-zju-lecture-note` 安装，
  或在本地目录先 `npm install --no-save --no-package-lock @deepseek-ai/schemastery@^3.18.1`
  再 `dsh plugin ... add file:<路径>`。
  插件现在会把这类错误翻译成「缺少依赖 + 该怎么装」，不再只抛裸的模块找不到。
- **Edge 登录态的两条死路**：Chromium 会对 Cookie 数据库加独占锁；Edge 127+ 若启用应用绑定加密（ABE），
  v20 Cookie 连 DPAPI 也解不开。插件会读 `Local State` 里的 `app_bound_encrypted_key` 判定 ABE，
  并在错误信息里直接指向 `ZJU_COOKIE_FILE`（而不是反复让你退出 Edge）；读库兜底复制会带上
  `-wal` / `-shm` 并让 SQLite 回放 WAL，避免"刚登录却被判未登录"。
- **PDF 课件**需要可选依赖 `pypdf`（`pip install pypdf`）；其余格式零依赖。
- **SSL / 代理**：信任库按 `certifi` → 随包 `cacert.pem` → 系统根证书 回落，所以 dsh 自带的无 certifi
  解释器也能正常握手；真正会失败的是**代理做了 HTTPS 解密**或**系统时间偏差过大**。错误消息会给出当前
  信任库、CA 张数、代理环境变量与具体修法（把 `classroom.zju.edu.cn` 设为直连或放进 `NO_PROXY`）。
  插件**不会**为了"能跑"而关闭证书校验。瞬时抖动（截断读包、握手 EOF、超时、5xx）已内置 3 次退避重试。
- **同名 Skill 的磁盘副本会抢名字**：若 `$DSH_HOME/skills/zju-lecture-summarizer/` 下还留着一份旧副本，
  一个名字只保留一份、重复的仅打 warning，Agent 可能一直读那份过期 SOP。SKILL.md 的 front matter 里
  **没有版本字段**，所以只能比内容：清单里的 `contentHash`（`sha256:...`）是权威值，插件启动时会在
  stderr 打印插件内置版与磁盘副本的 sha256，并给出删除路径。
- **讲义文件名不再固定**：1.4.1 起用 `zju_write_note`，文件名由 Agent 按「上课日期 + 本节内容」起名
  （`知识总结-2026-10-28-复变函数-保角映射.md`），缺省才回退 `知识总结-<sub_id>-<课程简称>.md`。
  固定的 `知识总结.md` 会让下一节课**静默覆盖**上一节，而讲义通常被 `.gitignore` 忽略、覆盖后无法恢复。
- **git 历史**：历史中已有的个人路径/密钥不会因为当前文件干净而消失；
  用 `python tools/privacy_scan.py --history` 检查，必要时重写历史并轮换凭证。
- **形态别选错**：`tools/build_plugin.py` 产出的是 **MCode 插件包**；装进 dsh 用的是本仓库根目录的
  npm 包（`dsh plugin ... add`）。两者是两套安装方式，不要混。
- 字幕接口公开，但请遵守平台条款：一次一节课，不要批量抓取。

## 许可与致谢

本插件改编自 [`nzw806/zju-lecture-summerizer-`](https://github.com/nzw806/zju-lecture-summerizer-)（MIT），
版权声明保留在 [`LICENSE`](LICENSE)。逐文件来源见 [`ATTRIBUTION.md`](ATTRIBUTION.md)。

仅供个人学习使用：只抓取本人有权限访问的回放，Cookie 属个人凭证，不要外传。

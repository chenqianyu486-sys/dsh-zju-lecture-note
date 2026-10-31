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

无论从哪种形态安装，Agent 看到的都是下面这 7 个工具。

## 隐私与安全（先看）

- **Cookie 不是工具参数**：`zju_fetch_slides` / `zju_get_video_url` 不接受 cookie 参数，
  `zju_read_browser_cookie` 也没有参数；登录态只能由本地配置（`ZJU_COOKIE` / `ZJU_COOKIE_FILE`）
  或本机 Edge 提供，模型无法把它写进参数或从返回值里读出来。
- **Cookie 不回显**：`zju_read_browser_cookie` 只返回名称、数量、长度与来源类别；
  所有 stdout / stderr / 错误消息还会再经过一次 redactor，注册过的 Cookie 值统一替换为 `[REDACTED]`。
- **Cookie 不落盘**：读 Edge 时优先只读打开数据库；必须复制时用 0600 私有临时文件，读完覆写并删除。
  服务端缓存只存在于 Python 子进程内存，进程退出即消失。
- **TLS 不降级**：证书校验永远不会被关闭；本机根证书不全时请求失败并提示安装 `certifi`，而不是"忽略证书错误"。
- **跨域重定向被拒绝**：避免 `urllib` 在 302 时把 `Cookie` 头重发到第三方域。
- **本地文件有边界**：`zju_extract_courseware` / `zju_check_note` 只接受课件与讲义扩展名，
  并拒绝 `.env`、凭据、私钥、浏览器 Cookie/Login Data 等敏感文件与目录。
- **不写用户目录**：插件把随包 Skill 注册到 dsh 技能表，而不是复制进 `$DSH_HOME`；无遥测、无后台服务。
- **可机器验证**：`python tools/privacy_scan.py` 扫描工作区，`--history` 扫描 git 历史，
  `--tarball` 扫描 npm 发布产物。

完整威胁模型与已知边界见 [`SECURITY.md`](SECURITY.md)。

## 工具清单

| 工具 | 功能 | 鉴权 | 隐私处理 |
| :--- | :--- | :--- | :--- |
| `zju_parse_url` | 解析回放链接，取 `sub_id` / `course_id` / `tenant_code` | 公开 | 纯字符串解析 |
| `zju_fetch_transcript` | 抓整节课或指定时间段的语音字幕，支持按分钟/逐句/分块/JSON 四种视图与字符上限 | **公开免登录** | 无 Cookie |
| `zju_fetch_slides` | 抓课堂投影的 PPT 文字层与 OCR | 需登录态（服务端本地解析） | 不收/不回显 Cookie |
| `zju_extract_courseware` | 提取本地 PPTX / DOCX / TXT / MD / CSV / JSON / PDF 文本 | 本地文件 | 拒绝敏感路径 |
| `zju_check_note` | 检查讲义 Markdown 的公式规范与渲染（可一键修复机械问题） | 本地文件 | 只接受 `.md` / `.markdown` |
| `zju_get_video_url` | 解析回放 MP4 直链（供下载或 Whisper 重识别） | 需登录态（服务端本地解析） | 直链可能带签名，勿外传 |
| `zju_read_browser_cookie` | 读取本机 Edge 登录态并缓存到服务端内存 | 本机读取 | **只返回名称与长度** |

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
`lib/index.js` 里的 `@deepseek-ai/schemastery` 是**普通依赖**（`dependencies`），
必须由 pnpm 装进 profile 的 `node_modules` 才会被解析到；解压出来的目录里没有
`node_modules`，启用时会报：

```text
Cannot find package '@deepseek-ai/schemastery' imported from ...\lib\index.js
```

若一定要用本地目录，先在目录里装好依赖，再让 dsh 加载：

```bash
cd /absolute/path/to/zju-lecture-agent-plugin
npm install --omit=peer        # 只装普通依赖；peer 由 dsh 运行时提供
dsh plugin --profile desktop add file:/absolute/path/to/zju-lecture-agent-plugin
```

`--omit=peer` 是必要的：peer 里的 `@deepseek-ai/dsh-*` 由 dsh 运行时提供，
让 npm 去 registry 装会因版本范围不匹配而失败。

装完后在 dsh 里直接说：

> 帮我把这节课整理成讲义：https://classroom.zju.edu.cn/livingroom?course_id=58133&sub_id=123456

> **版本要求**：dsh 会按 `peerDependencies` 中的 `@deepseek-ai/dsh-*` 范围校验运行时版本；
> 本插件声明 `>=0.2.0-rc.2 <0.3.0-0`，不匹配时需要显式的版本豁免。
> **Python 探测顺序**：插件配置项 → 环境变量 `ZJU_PYTHON` → DeepSeek Harness 自带 Python → PATH 上的 `python3` / `python` / `py -3`。

**登录态（可选，仅 PPT / 视频直链需要）**：优先自动读本机 Edge；Edge 正在运行时数据库被锁，
可在宿主配置里设置环境变量，**不要把 Cookie 粘贴到对话里**：

```bash
ZJU_COOKIE="name=value; name2=value2"        # 直接给 Cookie 头
ZJU_COOKIE_FILE="/absolute/path/cookie.txt"  # 或从本机文件读（一行，权限建议 600）
```

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
python -m zju_lecture.cli courseware ./课件.pptx
python -m zju_lecture.cli cookie            # 默认只显示名称与长度
```

> CLI 的 `cookie` 子命令默认**不回显明文**；确实需要时加 `--reveal`（会进入终端历史）。
> `slides` 子命令优先用 `--cookie-file` / `ZJU_COOKIE`；`--cookie` 仍可用，但会出现在进程列表里。

## 目录结构

```text
dsh-zju-lecture-note/
├── package.json                   # npm / dsh 插件包清单（包名 dsh-zju-lecture-note）
├── cordis.patch.yml               # dsh bundle patch（把插件插进 cordis）
├── lib/                           # dsh 插件实现（ESM）
│   ├── index.js                   # 插件入口：注册 7 个 dsh 工具 + 内存注册随包 Skill
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
7. 临时文件：只读打开优先；复制时 0600，读完覆写并删除。

### 本地文件

`zju_extract_courseware` 和 `zju_check_note` 只接受指定扩展名，并拒绝敏感文件名/目录
（`.env*`、`*credential*`、`*.pem`、`Cookies`、`Login Data`、`.ssh`、`.dsh` 等）。
符号链接会先解析真实路径再判定。确有必要时可用 `ZJU_ALLOW_SENSITIVE_PATHS=1` 显式关闭保护。

### 数据会离开本机的部分

字幕与课件文本会作为工具结果进入宿主模型上下文，由你选择的模型提供方处理——这是使用大模型
整理讲义的固有代价。插件本身不收集、不额外上传、不写遥测。

## 讲义的公式规范

生成的讲义要**能渲染**，而不只是"公式写对了"。插件把这件事做成了两道闸门：

1. **规范写进 Skill**（`skills/zju-lecture-summarizer/SKILL.md` §4④）——行内 `$...$` / 独立 `$$...$$`、
   分式 `\frac{分子}{分母}`（分子分母都带花括号）、绝对值 `\lvert ... \rvert`（不写裸 `|`）、
   虚数单位 `\mathrm{i}`、中文不塞进 `\text{}`、`<details>` 写成多行。
2. **产出后自检**——`zju_check_note` 静态扫描讲义，捕获"表格列被裸竖线截断""行内公式没闭合"
   "块级公式没独立成行""`\frac` 缺花括号""单行 `<details>`"这类会让整篇散架的问题。

```bash
python tools/check_note.py 讲义.md            # 只检查
python tools/check_note.py --fix 讲义.md       # 自动修正机械问题（单行 $$ 块、\dfrac、
                                              # \frac 补花括号、表格裸竖线、单行 <details>）
```

自动修复只做**语义无歧义**的改写；需要判断的（未闭合的 `$`、`\text{}` 里的中文、裸虚数单位）
保持原样并继续报出来。

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
python tools/smoke_test.py --sub-id <真实 sub_id>               # 对已安装包跑端到端冒烟（--dir 可指定包目录）
```

测试覆盖：URL 解析、时间戳格式化、分块时间区间回归、课件提取、工具 schema 健全性、
MCP 协议往返（`initialize` / `tools/list` / `tools/call` / 通知不响应）、
FIPS-197 AES-128 已知向量、Edge Cookie 失败原因分类、Cookie 主机精确匹配、Cookie 不回显与错误 redaction、
敏感本地文件拒绝、TLS 不降级、跨域重定向拒绝、讲义公式规范检查与自动修复、隐私扫描器自测。

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

## 已知限制

- **只解压 zip 就启用 → `Cannot find package '@deepseek-ai/schemastery'`**：
  dsh 插件是 pnpm 包，依赖得由 pnpm 装进 profile 的 `node_modules` 才会被解析到。
  用 `dsh plugin --profile desktop add github:chenqianyu486-sys/dsh-zju-lecture-note` 安装，
  或在本地目录先 `npm install --omit=peer` 再 `dsh plugin ... add file:<路径>`。
  插件现在会把这类错误翻译成「缺少依赖 + 该怎么装」，不再只抛裸的模块找不到。
- **Edge 正在运行时读不到登录态**：Chromium 会对 Cookie 数据库加独占锁，
  此时 `zju_read_browser_cookie` 会明确返回"请完全退出 Edge 后重试"，而不是含糊地说"未登录"。
  新版 Edge 的 v20 应用绑定加密在部分系统上仍可能无法本地解密，可改用 `ZJU_COOKIE_FILE`。
- **PDF 课件**需要可选依赖 `pypdf`（`pip install pypdf`）；其余格式零依赖。
- **SSL**：本机根证书不全时请求会失败并提示安装 `certifi`；插件**不会**为了"能跑"而关闭证书校验。
- **git 历史**：历史中已有的个人路径/密钥不会因为当前文件干净而消失；
  用 `python tools/privacy_scan.py --history` 检查，必要时重写历史并轮换凭证。
- **形态别选错**：`tools/build_plugin.py` 产出的是 **MCode 插件包**；装进 dsh 用的是本仓库根目录的
  npm 包（`dsh plugin ... add`）。两者是两套安装方式，不要混。
- 字幕接口公开，但请遵守平台条款：一次一节课，不要批量抓取。

## 许可与致谢

本插件改编自 [`nzw806/zju-lecture-summerizer-`](https://github.com/nzw806/zju-lecture-summerizer-)（MIT），
版权声明保留在 [`LICENSE`](LICENSE)。逐文件来源见 [`ATTRIBUTION.md`](ATTRIBUTION.md)。

仅供个人学习使用：只抓取本人有权限访问的回放，Cookie 属个人凭证，不要外传。

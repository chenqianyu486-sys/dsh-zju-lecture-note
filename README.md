# 浙大智云课堂 Agent Plugin（ZJU Lecture Summarizer）

> 把浙大智云课堂（`classroom.zju.edu.cn`）的课程回放变成一份可复习的结构化讲义：
> 语音字幕 + 课堂投影 PPT + 本地课件，交给宿主智能体做知识蒸馏。
> **字幕接口公开免登录**；零第三方依赖（纯 Python 标准库）。

本仓库同时是 **源码仓库** 和 **插件包源**：`server.mjs` + `mcp_server.py` + `skills/` 既是可运行的
MCP 服务，也是可直接安装的 MiniMax Code 本地插件包（`dsh` 同款形态）。

---

## 这是什么

上游项目 [`nzw806/zju-lecture-summerizer-`](https://github.com/nzw806/zju-lecture-summerizer-) 用
Python 脚本 + 本地网页 + 写死的 DeepSeek key 完成"链接 → 讲义"。本插件保留它的抓取内核，
把模型调度交给宿主智能体（Claude / GPT / DeepSeek / MiniMax Code …），并把整套流程封装成
标准 **MCP Server + Skill**：

| 维度 | 上游（CLI + 本地 Web） | 本插件（Agent Plugin / MCP） |
| :--- | :--- | :--- |
| 交互 | 固定单次生成网页，无法追问 | 原生 Tool / Skill，可多轮单点答疑、生成自测题 |
| 模型 | 脚本内硬编码 DeepSeek API | 宿主智能体直接感知材料，统一上下文与计费 |
| 生态 | 孤立工具 | 标准 MCP，可与 Git、知识库、文档插件协同 |
| 依赖 | 常驻后台 Web 服务 | 按需 stdio 进程，零 pip 依赖 |

复用与新增的具体边界见 [`ATTRIBUTION.md`](ATTRIBUTION.md)。

## MCP 工具清单

| 工具 | 功能 | 鉴权 |
| :--- | :--- | :--- |
| `zju_parse_url` | 解析回放链接，取 `sub_id` / `course_id` / `tenant_code` | 公开 |
| `zju_fetch_transcript` | 抓整节课或指定时间段的语音字幕，支持按分钟/逐句/分块/JSON 四种视图与字符上限 | **公开免登录** |
| `zju_fetch_slides` | 抓课堂投影的 PPT 文字层与 OCR | 需登录态（可自动读本机 Edge） |
| `zju_extract_courseware` | 提取本地 PPTX / DOCX / TXT / MD / CSV / JSON / PDF 文本 | 本地文件 |
| `zju_get_video_url` | 解析回放 MP4 直链（供下载或 Whisper 重识别） | 需登录态 |
| `zju_read_browser_cookie` | 读取本机 Edge 登录态（**默认不回显明文**，只在服务端缓存） | 本机读取 |

## 安装

### 1. MiniMax Code（本仓库推荐的形态）

```bash
python tools/build_plugin.py --install          # 校验 + 安装到 ~/.minimax/plugins/zju-lecture
python tools/build_plugin.py --install --zip    # 同时产出 dist/zju-lecture-<version>.zip
```

安装后 MiniMax Code 的插件自动扫描会识别该包，启用后即可直接说：

> 帮我把这节课整理成讲义：https://classroom.zju.edu.cn/livingroom?course_id=58133&sub_id=123456

卸载：删除 `~/.minimax/plugins/zju-lecture` 目录。

### 2. Claude Code

```bash
claude mcp add zju-lecture node /绝对路径/zju-lecture-agent-plugin/server.mjs
```

或把本仓库作为 Claude Code 插件目录使用（清单见
[`adapters/claude_code/plugin.json`](adapters/claude_code/plugin.json)）。

### 3. 任意 MCP 宿主

```json
{
  "mcpServers": {
    "zju-lecture": {
      "type": "stdio",
      "command": "node",
      "args": ["/绝对路径/zju-lecture-agent-plugin/server.mjs"],
      "timeout": 120000
    }
  }
}
```

`server.mjs` 会在运行时解析 Python 解释器（依次尝试 `python3` / `python` / `py -3`，要求 3.9+），
因此配置里只需要一个在 PATH 上必然存在的 `node`。

### 4. 命令行

```bash
python -m zju_lecture.cli parse "https://classroom.zju.edu.cn/livingroom?course_id=58133&sub_id=123456"
python -m zju_lecture.cli fetch 123456 --format min -o 字幕.txt
python -m zju_lecture.cli fetch 123456 --start 20 --end 45
python -m zju_lecture.cli courseware ./课件.pptx
python -m zju_lecture.cli cookie          # 读取本机 Edge 登录态
```

## 目录结构

```text
zju-lecture-agent-plugin/
├── .minimax-plugin/plugin.json      # MiniMax Code 插件清单
├── zju-lecture.mcp.json             # MCP 服务器定义（stdio → node ./server.mjs）
├── server.mjs                       # 启动器：解析 Python 解释器并拉起 MCP 服务
├── mcp_server.py                    # MCP stdio 服务器（JSON-RPC 2.0）
├── zju_lecture/                     # 核心库（纯标准库）
│   ├── client.py                    # 智云课堂 API 客户端
│   ├── cookies.py                   # Edge Cookie 读取与解密
│   ├── courseware.py                # 课件文本提取
│   ├── formatter.py                 # 时间戳 / 分钟聚合 / 分块
│   └── cli.py                       # 命令行入口
├── skills/zju-lecture-summarizer/SKILL.md   # 讲义生成 SOP（五段式模板）
├── adapters/                        # 其他宿主的接入示例（不进入插件包）
├── tests/test_plugin.py             # 回归测试
├── tools/build_plugin.py            # 校验 / 打包 / 安装
├── tools/export_schemas.py          # 从 TOOLS 重新生成适配器 schema
├── icon.png / icon-dark.png         # 插件图标
├── LICENSE / ATTRIBUTION.md
└── README.md
```

## 开发与测试

```bash
python -m unittest discover -s tests -v     # 全部回归测试
python tools/build_plugin.py --validate     # 按插件规范校验包结构
python tools/export_schemas.py              # 改动 TOOLS 后重新生成适配器 schema
```

测试覆盖：URL 解析、时间戳格式化、分块时间区间回归、课件提取、工具 schema 健全性、
MCP 协议往返（`initialize` / `tools/list` / `tools/call` / 通知不响应）、
FIPS-197 AES-128 已知向量、Edge Cookie 失败原因分类。

## 已知限制

- **Edge 正在运行时读不到登录态**：Chromium 会对 Cookie 数据库加独占锁，
  此时 `zju_read_browser_cookie` 会明确返回"请完全退出 Edge 后重试"，而不是含糊地说"未登录"。
  新版 Edge 的 v20 应用绑定加密在部分系统上仍可能无法本地解密，可改为手动传入 `cookie`。
- **PDF 课件**需要可选依赖 `pypdf`（`pip install pypdf`）；其余格式零依赖。
- **SSL**：若本机根证书不全，服务端会在 stderr 明确提示已降级为不校验证书。
- 字幕接口公开，但请遵守平台条款：一次一节课，不要批量抓取。

## 许可与致谢

本插件改编自 [`nzw806/zju-lecture-summerizer-`](https://github.com/nzw806/zju-lecture-summerizer-)（MIT），
版权声明保留在 [`LICENSE`](LICENSE)。逐文件来源见 [`ATTRIBUTION.md`](ATTRIBUTION.md)。

仅供个人学习使用：只抓取本人有权限访问的回放，Cookie 属个人凭证，不要外传。

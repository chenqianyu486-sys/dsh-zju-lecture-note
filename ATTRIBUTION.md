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

- 标准 MCP stdio 服务器（JSON-RPC 2.0）与 7 个工具定义；
- `server.mjs` 启动器：运行时解析 Python 解释器，跨平台统一用 `node` 启动；
- Skill 化的工作流 SOP；
- 协议级回归测试、FIPS-197 AES 已知向量测试、Edge Cookie 失败原因分类；
- MiniMax Code（MCode）插件包形态（`.minimax-plugin/plugin.json` + `zju-lecture.mcp.json`）；
- DeepSeek Harness（dsh）原生插件形态（本仓库根目录的 `package.json` + `cordis.patch.yml` + `lib/`，
  npm 包名 `dsh-zju-lecture-note`，与 MCP 形态共用同一份 Python 核心）；
- 隐私加固：Cookie 不进工具参数/返回值、全输出 redaction、Edge 数据库只读优先与安全清理、
  TLS 校验不降级、同域重定向限制、本地文件敏感路径拒绝、`tools/privacy_scan.py` 发布闸门。
  设计说明见 [`SECURITY.md`](SECURITY.md)。

## 声明

本项目仅供个人学习使用：抓取的是本人有权限访问的课程回放，频率极低。请遵守
浙江大学智云课堂的使用条款，不要用于批量抓取、传播课件或任何商业用途。
登录 Cookie 属于个人凭证，不要提交到任何仓库或发送给他人。

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

- 标准 MCP stdio 服务器（JSON-RPC 2.0）与 8 个工具定义；
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

v1.5.0 的智云投影 PPT 管线参考了以下 MIT 项目的公开实现思路，代码按本仓库的
纯标准库与安全边界重新实现：

| 项目 | 参考点 |
| :--- | :--- |
| [`8eoyw/zju-learning-cli`](https://github.com/8eoyw/zju-learning-cli)（MIT） | 从会话 Cookie 的 PHP 序列化值中解析 `_token` 并作为 `Authorization: Bearer`；`search-ppt` 的 `course_id` + `page/per_page` 分页与按 URL 去重；截图合成 PDF；ZJU `http://` 升级 HTTPS。 |
| [`PeiPei233/zju-learning-assistant`](https://github.com/PeiPei233/zju-learning-assistant)（MIT） | 智云课堂 API 流程的原始来源（本项目最早即改编自其上游移植）。 |

本仓库只实现了**连续字节完全相同**的截图折叠；`zju-learning-cli` 基于 numpy/Pillow 的
“笔画是否仍存在于后续页面”近似去重没有移植——那会打破本插件零第三方依赖的约束。

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

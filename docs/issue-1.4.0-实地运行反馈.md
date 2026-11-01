# [运行反馈] 1.4.0 真实一节课跑下来遇到的 8 个问题（含复现与代码定位）

> 用途：可直接粘贴为 GitHub issue 正文。
> 仓库：`chenqianyu486-sys/dsh-zju-lecture-note`　版本：`1.4.0`　环境：Windows 10 + DSH Web GUI
> 现场案例：`sub_id=1988057`（复变函数与积分变换，保角映射 + 拉普拉斯变换，时长 `01:43:49`，872 句字幕）
> 全流程：`zju_parse_url` → `zju_fetch_transcript`（per_minute → per_segment）→ `zju_fetch_slides`（失败）→ 写 `知识总结.md` → `zju_check_note`（2 轮 + 1 次外部脚本才通过）

## TL;DR

流程整体能跑通，最终产出的讲义 `zju_check_note` **0 错 0 警**。但过程中有 2 个问题直接卡住操作
（相对路径失效、`fix=true` 少一类确定性修复），另有 6 个问题增加噪音、污染工作区或诱导违规操作。
下面按严重度排列，P1 = 卡住 / 需绕过，P2 = 显著增加摩擦，P3 = 打磨项。

---

## P1-1　`zju_check_note` 相对路径解析依赖服务进程 cwd，不是 session workspace

**现象**

```
zju_check_note(file_path="知识总结.md")
→ 错误: 找不到讲义文件: 知识总结.md
```

文件确实就在 session workspace 根目录（`C:\...\zju-lecture-agent-plugin\知识总结.md`）。
换成绝对路径立刻成功：

```
zju_check_note(file_path="<workspace>\知识总结.md")
→ === 讲义渲染规范检查 (知识总结.md) === ...
```

**定位**：`mcp_server.py:567`

```python
if not os.path.isfile(os.path.expanduser(file_path)):
    return f"错误: 找不到讲义文件: {file_path}"
```

`mcp_server.py` 全文没有出现过 `workspace` / `cwd`（`grep -rn "workspace\|cwd" mcp_server.py` 无命中），
即相对路径只按 MCP 服务进程的启动目录解析。而 Agent 的"当前工作目录"与 MCP 进程 cwd 不必相同
（本次 DSH 会话 workspace 是插件仓库根目录，服务端 cwd 是别的目录）。

**影响**：Agent 侧表现为"文件明明存在但工具说找不到"，只能退回绝对路径；一旦宿主换目录就再次失败。
更糟的是错误信息不提示"我尝试解析到了哪里"，Agent 很难自查。

**建议**
1. 解析顺序改为：绝对路径 → session workspace 相对路径（可由宿主传入的 root，或 `ZJU_WORKSPACE` 环境变量）→ 进程 cwd；
2. 失败时在错误里回显**已尝试的候选绝对路径**与服务端 cwd，例如
   `错误: 找不到讲义文件: 知识总结.md（尝试过: <cwd>/知识总结.md, <ws>/知识总结.md）`；
3. 补一条单测：`test_plugin.py:367` 目前只断言了报错文案存在，没有覆盖"相对路径应能在 workspace 内解析成功"。

---

## P1-2　`fix=true` 不覆盖 `display_not_isolated`，59 处必须外部脚本补空行

**现象**：一次写完 ~460 行的讲义，`zju_check_note(fix=true)` 修掉了 35 处分式写法
（`\dfrac -> \frac`、`\frac` 补花括号），但 59 处 `display_not_isolated` 一条没修，仍判"不通过"：

```
=== 已自动修复 ===
- 统一 35 处分式写法（\dfrac -> \frac、\frac 补花括号）
=== 讲义渲染规范检查 ===
错误 59 | 警告 0
[错误] L108 · display_not_isolated
  问题: 块级公式 `$$` 之前必须留一个空行
```

这 59 条的错误模式完全一致：`$$` 独占一行、但**前一/后一行是正文**（P 段落、列表项、`**加粗标题**`）。

**定位**：
- 检查在 `zju_lecture/note_lint.py:91-111`（开 `$$` 看 `lines[idx-2].strip() != ""`，闭 `$$` 看 `lines[idx].strip() != ""`）；
- 修复器 `fix_markdown`（`note_lint.py:368-447`）的 `applied` 只有 4 类：单行 `$$...$$` 拆三行、分式、表格裸竖线、单行 `<details>`；
  **没有** "给多行 `$$` 块补前后空行" 这一项。

**为什么这条值得修**：这是**纯确定性**重写（插入一个空行，不改变任何公式语义、不需要人类判断），
而它恰恰是最容易成批出现的一类——长讲义里只要少写空行，就一次性产出几十条同类错误。
本次只能现场写 Python 脚本绕过：

<details>

<summary>本次绕过用的脚本（可作 fixer 实现参考）</summary>

```python
lines = text.split("\n")
out, inside = [], False
for ln in lines:
    s = ln.strip()
    if s == "$$":
        if not inside:                       # 开块：保证前面有空行
            if out and out[-1].strip() != "":
                out.append("")
            out.append(ln); inside = True
        else:                                # 闭块：保证后面有空行
            out.append(ln); out.append(""); inside = False
        continue
    out.append(ln)
# 再折叠连续空行
```

注意两点实现细节：
1. **不能对每个 `$$` 行都前后插空行**——那会把空行插进公式体内部（`$$` / body / `$$` 之间），可能破坏 KaTeX 的多行块；
   必须用 `inside` 状态区分开块 / 闭块。
2. **要跳过 fenced code block**（```` ``` ```` 区域内），否则文档里示范 `$$` 的代码示例会被改写。
   现有 `fix_markdown` 已有 `in_fence` 逻辑，直接复用即可。
3. 建议顺带**保留缩进**：列表项内的 `$$` 目前会被拆出列表（我这次脚本没处理缩进，`### 4` 那节的 1./2. 两条被公式块切开了）。
   官方 fixer 可对列表内 `$$` 补 `indent`（`re.match(r"^(\s*)", line)`）。

</details>

**建议**：在 `fix_markdown` 增加 `display_isolated` fixer，`applied` 里报
`"为 N 处块级公式补全前后空行"`，并补两类测试：开块前缺空行、闭块后缺空行；外加"公式体内不得被插空行"的回归测试。

---

## P2-1　检查报告不聚合，91 条逐条打印，上下文开销过大

**现象**：上面那次 `zju_check_note` 返回 **59 错 + 32 警 = 91 条**，每条打印 `问题` / `修法` / `原文` 三行
（`note_lint.py:239-246` 的循环无任何去重或上限）。同一条 `display_not_isolated` 的 `问题`/`修法` 文本重复 59 次，
单次工具返回占掉可观上下文——对 agent 来说这是纯噪声，还会挤压后续生成预算。

**定位**：`format_report`（`zju_lecture/note_lint.py:224-252`）逐条 append，无按 `code` 聚合、无 `max_items`。

**建议**：按 `code` 聚合并给出代表样例，例如

```
[错误] display_not_isolated × 59
  问题: 块级公式 `$$` 前后必须各留一个空行
  修法: ...
  首次出现: L108；示例:
    L108 <上一行正文摘要>
    L110 ...
  （其余 57 处已省略）
```

可选参数：`summary_only` / `max_items`（默认 10/类）。这样 `fix=true` + 聚合报告基本能一轮收敛。

---

## P2-2　`zju_fetch_slides` 无 Cookie 分支消息拼接混乱，且给出自相矛盾的建议

**现象**（本次真实返回，原文照抄）：

```
未抓取到 PPT 记录。可能原因：
Edge 正在运行，Cookie 数据库被独占锁定，无法读取。
请完全退出 Edge（包括后台驻留进程）后重试；本机 Edge 已启用应用绑定加密（ABE），退出 Edge 也无法在本地解密，请改用 ZJU_COOKIE_FILE 环境变量（文件内只放一行 Cookie 头）。
2. 老师授课时未通过智云课堂课件系统同步投影
（流水线可平滑降级，仅依赖语音字幕完成讲义生成）
```

三个问题一起出现：

1. **缺 "1."**：分支里硬编码了 `"2. 老师授课时…"`（`mcp_server.py:500`、`513`），
   而第 1 条是由 `cookie_error` 变量拼进来的，编号对不上；
2. **同一句话自相矛盾**：`zju_lecture/cookies.py:474-479` 先写"请完全退出 Edge（包括后台驻留进程）后重试；"
   紧接着又写"已启用 ABE，退出 Edge 也无法在本地解密"。ABE 场景下前半句是**无效建议**，用户按做纯属白跑；
3. **把"能诊断的具体原因"和"也许真实存在的另一可能"平铺成一串**，agent 无法判断该走哪条路
   （本次实际是 `locked + ABE`，PPT 有无投影根本未探测——却把"没投影"也列进可能性）。

**建议**
1. 拆成两个互斥结论：`reason="cookie_locked" | "cookie_abe" | "no_credentials" | "no_slides"`，
   只输出命中的那一个 + 对应的唯一动作；ABE 命中时**不要**输出"退出 Edge 重试"；
2. 编号要么统一由模板生成（`1. … 2. …`），要么全部不要编号；
3. 若确实想表达"即使拿到 Cookie 也可能没投影"，请作为独立一句提示，不混进原因列表。

---

## P2-3　默认输出名 `知识总结.md` 会静默覆盖历史讲义，且被 `.gitignore` 忽略（不可恢复）

**现象**：本次按 Skill 步骤二写入 `知识总结.md` 时，覆盖掉了上一节课的讲义——
文件里原本是 `sub_id=1988617`（运算放大器 + 二极管）的 354 行笔记。因为 `.gitignore` 里有
`/知识总结*.md`，该文件未被版本控制跟踪，**覆盖后无法恢复**（本次只能靠人工重抓字幕重做）。

**定位**
- `skills/zju-lecture-summarizer/SKILL.md:67`：`"按第 4 节的规范把字幕蒸馏成讲义，写入 知识总结.md"`——固定文件名；
- `.gitignore` 的 `/知识总结*.md` 使覆盖对 git 完全不可见。

**建议**
1. Skill 文案改成带标识的文件名，例如 `知识总结-<sub_id>-<课程简称>.md`（或 `notes/<sub_id>/知识总结.md`）；
2. 或提供 `zju_write_note(sub_id, content)` 工具统一命名 + 覆盖前要求确认（已有文件则返回 `exists`，让 agent 决定改名/覆盖）；
3. `.gitignore` 放宽为 `知识总结-*.md` 之类，避免"所有讲义都不可恢复"这一刀切。

---

## P3-1　`fix=true` 的 `.bak` 落在工作区，污染 `git status`

**现象**：`fix=true` 后仓库里出现未跟踪文件 `知识总结.md.bak`，`git status` 直接多一项：

```
?? "\347\237\245\350\257\206\346\200\273\347\273\223.md.bak"
```

**定位**：`mcp_server.py:586` `backup_path = file_path + ".bak"`，与讲义同目录。

**建议**：`.gitignore` 加一条 `*.md.bak`；或把备份写到系统临时目录 / 插件 `output/tmp/` 下
（`output/` 已被忽略），返回里给出备份的绝对路径。

---

## P3-2　安装到 `~/.dsh/skills` 的副本与仓库 `skills/` 漂移，旧文案诱导违反隐私边界

**现象**：本次实际加载的是 `~/.dsh/skills/zju-lecture-summarizer/SKILL.md`，其第 61-62 行是：

```
未提供登录态时服务会尝试读取本机 Edge；若返回"Edge 正在运行，Cookie 数据库被独占锁定"，
**请提示用户完全退出 Edge（含后台驻留进程）后重试**，或让用户手动提供 cookie 参数。
```

而仓库版 `skills/zju-lecture-summarizer/SKILL.md:62-63` 已经修正为：

```
…**请提示用户完全退出 Edge（含后台驻留进程）后重试**，
或在宿主配置里设置 ZJU_COOKIE / ZJU_COOKIE_FILE；**不要让用户把 Cookie 粘贴进对话，也不要把 Cookie 写进讲义或命令参数**。
```

差异有实质影响：
1. 旧文案"让用户手动提供 cookie 参数"——**工具根本没有 cookie 参数**
   （`zju_fetch_slides` / `zju_fetch_video_url` 的 schema 里没有，且工具描述明说"不接受也不回显 Cookie"），
   agent 照做会去索要 Cookie，**直接撞 `SECURITY.md` 的隐私边界**；
2. 旧文案同时缺"不要粘贴进对话"这句护栏；且没提 ABE 下"退出 Edge 也无效"（与 P2-2 同源）。

**建议**
0. 补充事实：`SKILL.md` 的 front matter **只有 `name` / `description`，没有 version 字段**，
   所以这种漂移从 Skill 侧完全看不出来。本次实测两份文件 sha256 不同、体积差 1175 字节：

   ```
   527c79… 11942  skills/zju-lecture-summarizer/SKILL.md              （仓库，已修正）
   a785d2… 10767  ~/.dsh/skills/zju-lecture-summarizer/SKILL.md       （本机安装副本，旧文案）
   ```

1. 安装脚本/文档里加"覆盖安装前校验 SKILL.md 内容哈希"的提示（光比版本号发现不了，因为根本没有）；
2. 给 Skill manifest 加一个 `contentHash` 字段，`zju_*` 启动时或 `skill_status` 里比对并警告"本地副本与插件版本不一致，请重新安装"；
3. 仓库侧加一条测试：断言 SKILL.md 里不出现 `手动提供 cookie` 这类诱导文案（防回归）。

---

## P3-3　字幕 ASR 质量没有任何信号，讲义只能靠人工判断"哪里不可信"

**现象**：本次字幕质量相当差，大量口语碎片与错字，关键处几乎不可直读，例如：

- `[01:04]` "第7章题目叫拉普拉斯变换。病患love plus数学家病患，那到底是个啥病患呢？"（"变换"全被识别成"病患"）
- `[00:39]` "无穷远点对应的是什么点N趋向于无穷啊。懂我有无交易的是不是东西到圆顶啊"
- `[01:23]` "哎，S最后的结论是这个结论啊，又半个平米啊"（"右半平面"）

若照字面直译会**产出错误讲义**。本次的处理是：凡涉及表达式的推导全部按数学规范复算校核，
两处无法还原的（`00:43` 内外判断、`00:46` 考题参数）在正文用 `⚠` 标注并给出复算结论。

**建议**
1. `zju_fetch_transcript` 返回一个轻量质量指标，例如
   `quality: {noise_ratio: 0.42, repeated_tokens: ["嗯","对","这个"], hint: "ASR 质量偏低，公式与术语需人工复核"}`，
   让 agent 在"复算校核 / 加免责说明"上做出判断，而不是靠 luck；
2. Skill 第 4 节①「极致降噪」增加一条硬性要求：**字幕噪声明显时，讲义顶部必须写明 ASR 限制与需复核的具体时间点**（本次已这样做，建议模板化）；
3. 长期方案：既然已有 `zju_get_video_url` + Whisper 增强路径，可在 Skill 里补一句"ASR 质量差且关键公式密集时，建议走 Whisper 重识别"。

---

## 已验证**非**缺陷（避免误报）

顺手核一下，避免别人再花时间：

- `zju_parse_url` 正常：`course_id=87207 / sub_id=1988057 / tenant_code=112` 全部解析正确。
- `zju_fetch_transcript` 的 **`per_minute` 时间戳是对的**（`formatter.py:63` 用绝对分钟索引 `f"[{h:02d}:{mn:02d}]"`，
  会正确跨过 60 分到 `[01:04]`）。我一开始被"总时长 `01:43:49` 而末段标签可读性弱"迷惑，多抓了一次 `per_segment` 交叉验证——工具没问题，是我误判。
- `zju_fetch_transcript` 的 `start_minute`/`end_minute` 切片、`per_segment` 秒级时间戳均准确，`447 句 / 00:00:08–00:53:56` 与 `69 句 / 01:35:04–01:43:49` 都对得上。
- `zju_check_note` 的 `fix=true` 对 `\dfrac -> \frac` 的修复、`.bak` 备份原子写、`结论: 通过` 判定都工作正常。

---

## 建议的修复顺序（最小改动版）

1. **P1-2** `display_isolated` fixer（~30 行 + 3 个测试）——收益最大，直接消灭本次 59/91 条噪音来源；
2. **P1-1** 相对路径按 workspace 回退 + 错误回显候选路径（~10 行 + 1 个测试）；
3. **P2-1** `format_report` 按 code 聚合（~20 行，改 2 处断言）；
4. **P2-2** slides 失败分支结构化（`reason` 枚举，~20 行）；
5. **P3-1** `.gitignore` 加 `*.md.bak`（1 行）；
6. **P2-3 / P3-2 / P3-3** 属 Skill 文案 + 命名约定，可与下一版一起发。

改完建议跑：`python -m unittest discover -s tests`、`node tests/bridge_smoke.mjs`、`python tools/privacy_scan.py`
（本次源码只看未改，未跑测试）。

## 附：本次实际产出的讲义

`知识总结.md`（覆盖了 1988617 的旧讲义，见 P2-3），`zju_check_note` 终态 **错误 0 / 警告 0 / 结论: 通过**。

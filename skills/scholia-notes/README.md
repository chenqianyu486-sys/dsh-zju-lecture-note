# scholia-notes

把 STEM 内容做成**填空式学习笔记**的 Agent Skill：先用 Markdown 把内容和结构写完整，
再套 Typst 的 [scholia](https://typst.app/universe/package/scholia) 模板排版，
本地编译校验为 PDF / PNG。

> 本 skill 与 `scholia` 包的作者、发行方无关，也未获其背书。

## 它做什么

- **两段式**：内容与排版分离。底稿（Markdown）可以独立阅读、独立修改，排版只是它的一次实现。
- **淡彩极简**：正文近黑，强调靠行内淡色加粗，方框只在真的需要编号回指时才出现。
  四个强调色的 WCAG 对比度极差 ≤ 1.2，视觉等权。
- **主动回忆**：`[练习]` 留白、`[边注]` 右栏提问、`____` 填空线、`[证明]` 骨架留缺口。
- **可验证**：编译输出 `error:` 一条都不能留；knot 的内容块数量错位**不会报错**，
  所以必须看逐页 PNG —— 这一点写进了 SOP，不是可选项。

## 在 `dsh-zju-lecture-note` 插件里（推荐）

插件已内置本 skill，并把两段式流程工具化：

```text
zju_build_study_notes(mode="draft",   note_path="知识总结-….md")
    → 知识总结-…-填空底稿.md          # 标题层级映射 + 标记位插入 + LaTeX 数学 → Typst 数学
（你把标记位填成真正的定义 / 定理 / 练习）
zju_build_study_notes(mode="compile", draft_path="知识总结-…-填空底稿.md")
    → main.typ + prelude.typ + out.pdf + page-N.png
```

工具只做搬运与排版；**哪些是定理、哪里该挖空仍然是内容判断**。
它会把「无法机械转换的数学」「超出视觉预算的方框」「编译错误」原样报出来。

## 单独使用（不装插件）

把本目录放进你的 Agent skill 目录（Claude Code / MCode 的 `skills/`），然后：

1. 按 `SKILL.md` 写 `notes.md` 底稿；
2. 复制 `references/prelude.typ` 到项目目录，写 `main.typ`（顶部三行固定）；
3. `typst compile main.typ out.pdf` 与 `typst compile main.typ "page-{p}.png"`。

前置条件：已安装 Typst ≥ 0.13.0（`typst --version`）。

## 目录

```text
SKILL.md                    工作流 SOP（主文档）
LICENSE                     MIT
THIRD_PARTY_NOTICES.md      上游包与字体的逐条归属
references/prelude.typ      淡彩 palette + 五个助手（生成副本，单一来源在 zju_lecture/）
references/starter.typ      起步模板
references/api.md           上游 API 参考（基于实测源码）
references/mapping.md       Markdown 底稿 → Typst 映射表
references/style.md         风格指南与视觉预算
references/troubleshooting.md  排错记录
```

## 许可

本 skill 以 **MIT** 发布（见 [`LICENSE`](LICENSE)）。
排版引擎 `@preview/scholia` 为 MIT © Eric Yang，编译期由 Typst 包注册表拉取，未随本仓库分发。
逐条归属见 [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md)。

# PR: Add chenqianyu486-sys/dsh-zju-lecture-note

**Title**

```
Add chenqianyu486-sys/dsh-zju-lecture-note (docs)
```

**Body** (paste into the PR; tick the template boxes)

```markdown
## Summary

Adds one file — `data/plugins/chenqianyu486-sys__dsh-zju-lecture-note.yml` (`category: docs`).

[dsh-zju-lecture-note](https://github.com/chenqianyu486-sys/dsh-zju-lecture-note) turns
Zhejiang University Zhizhi Classroom replays (`classroom.zju.edu.cn`) into Markdown study
notes. Its scraping core comes from
[`nzw806/zju-lecture-summerizer-`](https://github.com/nzw806/zju-lecture-summerizer-)
(a standalone Python tool, not a DSH plugin), and the slide capture follows
[`8eoyw/zju-learning-cli`](https://github.com/8eoyw/zju-learning-cli) (MIT), reimplemented
here without copying code. It reads the public speech transcript (per-minute, per-sentence or
chunked) and can download the projected slide screenshots as a PDF to reference selected
pages; that slide capture needs a ZJU login state (`ZJU_COOKIE` / `ZJU_COOKIE_FILE` or a local
Edge profile), while transcript reading is public. It writes a note named after the class date
and section, checks that note's Markdown so formulas and tables render, and renders the same
note to a PDF locally with Typst. The optional fill-in study notes are typeset with the
MIT-licensed [scholia](https://typst.app/universe/package/scholia) Typst template by Eric
Yang; their color and paragraph specs are this project's own (see the scholia-notes spec).
The reading PDF uses a self-contained template that follows scholia's light-theme design
without copying source. This project is not affiliated with or endorsed by the upstream author.

Not on npm yet, so the install command is the GitHub one:

```sh
dsh plugin --profile desktop add github:chenqianyu486-sys/dsh-zju-lecture-note
```

## What the code is

- `package.json` declares `dsh.bundle` → `./cordis.patch.yml`; the patch inserts one plugin
  id (`dsh-zju-lecture-note`). No build step, no postinstall script.
- `lib/` registers the tools from `lib/tools.schema.json` and spawns the Python core as a
  child process (session workspace passed as cwd and `ZJU_WORKSPACE`).
- `zju_lecture/` is the extractor (Python standard library only; optional `pypdf` for PDF
  courseware; a bundled `cacert.pem` so TLS verification does not depend on a `pip install`).
- `skills/zju-lecture-summarizer/` is the note SOP registered as a skill (not copied into
  `$DSH_HOME`).
- `README.md` documents each tool, the Python discovery order and the privacy boundary;
  `SECURITY.md` is the threat model; `python tools/privacy_scan.py` re-checks the workspace,
  the git history and the packed artifact.

## Checklist

- [x] Added one file at `data/plugins/<owner>__<repo>.yml`; READMEs untouched (regenerated on `main`)
- [x] `package.json` declares `dsh.bundle` (`{"patch": "./cordis.patch.yml"}`), not just `dsh.client`
- [x] Repository created 2026-10-30 — more than 1 day old
- [x] `category: docs` — the deliverable is a rendered Markdown 讲义 (the plugin also checks
      that its formulas and tables render). Move it to `skill` if you read it as the SOP
      skill being the main thing; no objection.
- [x] Description states what the plugin does; no superlatives. It also names the upstream
      scraping core (`nzw806/zju-lecture-summerizer-`, a standalone Python tool) and states the
      login prerequisite *and* the opt-in gate for the slide capture. Every claim maps to
      `lib/tools.schema.json` / `zju_lecture/` (`fetch_transcript` is the public, login-free
      endpoint; slides and the video URL are the two tools that need a login, read from local
      config or the local Edge profile rather than from a tool argument)
- [x] `dsh-plugin` topic added to the repository
- [x] `icon:` points at `icon.png` in this repository (256×256 PNG, GitHub raw)

## Review follow-up (2026-11-02)

`held: author` asked for two things in the entry description: name the upstream project, and
state that the projected-slide capture needs a login state. Both are in the `en` / `zh` lines
now, and the slide pipeline's reference implementation
([`8eoyw/zju-learning-cli`](https://github.com/8eoyw/zju-learning-cli), MIT, no code copied)
is credited too — `ATTRIBUTION.md` lists it under 参考实现（未拷贝代码）.

The version the entry describes was pushed to `main` the same day (1.5.0: slide screenshots +
optional PDF), so the wording matches the code a reviewer installs: the slide endpoint returns
screenshots, not a text layer, so the entry says "download the projected slide screenshots as
a PDF" instead of "read the projected slides".

**Update — 1.5.1 (2026-11-02).** `main` has since shipped 1.5.1, which decouples the transcript
path from the slide module: `zju_fetch_slides` is now **opt-in** (`enableSlides`, default
`false`; Settings → 「浙大智云课堂讲义」), so a fresh install gets the public, login-free
transcript tools and nothing that touches a login. The entry now says the slide capture is
opt-in as well, so its claim still matches what a reviewer sees after installing `main`.
The transcript main path is unchanged.

**Update — 2.0.2 (2026-11-03).** The entry now credits the PDF template too. Reading notes are
rendered to a same-name PDF locally (cover, table of contents, sidenotes); the optional
fill-in study notes are **typeset with the MIT-licensed
[`@preview/scholia`](https://typst.app/universe/package/scholia) Typst template by Eric Yang**,
with this project's own color and paragraph spec (see `skills/scholia-notes/references/typography-spec.md`).
The reading-note template is this project's own (`zju_lecture/handout_prelude.typ`, self-contained,
no upstream import); it follows scholia's light-theme design without copying source. The entry
says both things, plus "not affiliated with or endorsed by" the upstream author. Full per-file
attribution is in `ATTRIBUTION.md` and `skills/scholia-notes/THIRD_PARTY_NOTICES.md`.

The 2.0.2 code is pushed to `main` alongside this entry update, so what a reviewer installs
matches the description.

## Privacy boundary (worth knowing before reading the diff)

The login cookie is never a tool parameter and is never returned: the read-cookie tool
reports only name / count / length / source, all stdout+stderr goes through a redactor, and
the local-file tools refuse credential and browser-data paths. Details in `SECURITY.md`.
```

**Reviewer-visible facts I checked against the list's CI**

| CI step | Result |
| --- | --- |
| Entry count ≤ 3 | 1 |
| `dsh.bundle` in the repo's `package.json` | present on `main` |
| Repo age ≥ 1 day | created `2026-10-30T03:02:39Z` |
| Entry shape / filename / category / locales | `node scripts/... entries.mjs` → 0 problems |
| `generate-readme.mjs` | row generated in both `README.md` and `README.zh.md` |
| Duplicate check | no existing entry for this repo; nearest neighbours are `YLL-KB/dsh-video-to-notes`, `logb-1/dsh-course-assistant`, `Chenfan2/dsh-bilibili-subtitles` |
| `dsh-plugin` topic | set |

## 2.1.0 follow-up — dependency bundling

The plugin is now self-sufficient for PDF output:

- six `@preview` Typst packages are vendored under `zju_lecture/typst-packages/` **together with
  their `LICENSE` / `UNLICENSE` and `typst.toml`**, so the fill-in-notes PDF compiles offline;
- a redistributable OFL CJK font subset (`Notes Serif SC`, renamed to avoid clashing with a locally
  installed Noto Serif SC) ships in `zju_lecture/fonts/` with `OFL.txt` and `FONT-NOTICE.md`;
- if Typst itself is missing, the plugin downloads the official release on first use
  (about 20 MB, SHA256-pinned, opt-out via `typstAutoInstall`), and the new `zju_doctor` tool
  reports the local state.

The entry description was updated accordingly: it no longer claims "no upstream code is copied"
as a blanket statement — the reading template is still original, while the six upstream packages
are now vendored with their licence files.

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
and section, and checks that note's Markdown so formulas and tables render.

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
      login prerequisite for the slide capture. Every claim maps to `lib/tools.schema.json` /
      `zju_lecture/` (`fetch_transcript` is the public, login-free endpoint; slides and the
      video URL are the two tools that need a login, read from local config or the local Edge
      profile rather than from a tool argument)
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

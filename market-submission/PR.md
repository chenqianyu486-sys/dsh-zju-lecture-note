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
notes: it reads the public speech transcript (per-minute, per-sentence or chunked),
optionally downloads the projected slide screenshots as a PDF and can reference selected pages
in the note, or reads the student's local courseware, writes a note named after the class date
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
- [x] Description states what the plugin does; no superlatives. Every claim maps to
      `lib/tools.schema.json` / `zju_lecture/` (`fetch_transcript` is the public, login-free
      endpoint; slides and the video URL are the two tools that need a login, and both read
      it from local config or the local Edge profile instead of taking it as an argument)
- [x] `dsh-plugin` topic added to the repository
- [x] `icon:` points at `icon.png` in this repository (256×256 PNG, GitHub raw)

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
| Repo age ≥ 1 day | created `2026-10-30T03:02:39Z` (≈2.5 days at submission) |
| Entry shape / filename / category / locales | `node scripts/... entries.mjs` → 0 problems |
| `generate-readme.mjs` | row generated in both `README.md` and `README.zh.md` |
| Duplicate check | no existing entry for this repo; nearest neighbours are `YLL-KB/dsh-video-to-notes`, `logb-1/dsh-course-assistant`, `Chenfan2/dsh-bilibili-subtitles` |
| `dsh-plugin` topic | **not yet set** — see 提交说明.md step 1 |

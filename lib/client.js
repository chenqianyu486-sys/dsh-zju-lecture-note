/**
 * Browser half of dsh-zju-lecture-note.
 *
 * The same page is mounted twice, from two seats the shell owns:
 *
 *   - `settings.section` — 设置 → 浙大智云课堂讲义 (the deep link), id `zju-lecture`;
 *   - `sidebar.panellist` + `main` — the left-column row 智云讲义, whose click
 *     selects the global panel registered under the same id.
 *
 * Both render one component over one `PipelineSettings` controller, so a switch
 * moved in either place shows up in the other without a reload.
 *
 * The page is built around the actual pipeline — 字幕 → 讲义 → PDF — and every
 * optional module is a separate switch with its own dependency and cost, so a
 * user can see what they are turning on before they turn it on.
 *
 *   - `renderPdf`         auto-typeset the written note into a reading PDF
 *   - `enableStudyNotes`  fill-in study notes (+ scholia-notes Skill)
 *   - `enableSlides`      projected-slide capture
 *   - `embedSlideImages`  reference those screenshots in the note
 *   - `enableLoginTools`  video URL / Edge-cookie helpers
 *   - `typstAutoInstall`  install Typst on first use
 *   - `typstPath` / `typstMirror`  pin the executable or a download mirror
 *   - `python` / `timeoutMs` / `registerSkill`  advanced interpreter controls
 *
 * Volatile values are live: the plugin re-syncs tools, Skills, the prompt and
 * its Python children when one is saved, so the agent reads the new setting on
 * its next turn. The page therefore does not ask the user to restart dsh for a
 * switch — only a plugin install/update still needs a restart.
 *
 * The Host exposes only `Config` fields marked `.volatile()`. Writes go
 * through the shared `configForms` scope, so they carry the current revision
 * and are refused rather than clobbering a newer value. Plain JavaScript,
 * React from the host module table, no build step.
 */

window.__ModuleLoader__.load({
  id: 'dsh-zju-lecture-note',
  factory(require) {
    const React = require('react')
    const h = React.createElement

    const NS = 'dsh-zju-lecture-note'
    /**
     * One id for both left-column seats: `sidebar.panellist` renders the row,
     * `main` renders the page the row opens. The sidebar dispatches
     * `ctx.layout.selectPanel(id)`, so the two registrations must agree.
     */
    const PANEL_ID = 'zju-lecture'
    const CANDIDATE_NAMESPACES = [
      'include:dsh-zju-lecture-note',
      'dsh-zju-lecture-note',
    ]

    const en = {
      sectionTitle: 'ZJU classroom lecture notes',
      panelLabel: 'ZJU notes',
      panelNote: 'Also available in Settings → ZJU classroom lecture notes.',
      eyebrow: 'ZJU · CLASSROOM',
      heroTitle: 'Turn a replay into review-ready notes',
      heroBody: 'Transcripts are anonymous first; 401/403 retries once with the local login. PDF typesetting runs locally.',
      pipelineTranscript: 'Transcript',
      pipelineNotes: 'Markdown notes',
      pipelinePdf: 'Reading PDF',
      toolCountLabel: 'tools',
      toolsNowPrefix: 'This config registers',
      toolsNowSuffix: 'tools',
      pdfOn: 'PDF on',
      pdfOff: 'PDF off',
      presetsTitle: 'Presets',
      presetToken: 'Token saver',
      presetStudy: 'Study mode',
      presetFull: 'Everything',
      presetTokenHint: 'PDF only',
      presetStudyHint: 'PDF + fill-in notes',
      presetFullHint: 'All modules',
      coreTitle: 'Core pipeline',
      coreBadge: 'Always on',
      coreRowTitle: 'Transcript → notes → linting',
      coreRowHint: 'No configuration required.',
      outputTitle: 'Reading output',
      outputBadge: 'Recommended',
      outputBody: 'Markdown is the source; the PDF is the reading copy.',
      pdfTitle: 'Auto-typeset PDF',
      pdfHint: 'After each note write, typeset the same Markdown into a print-ready PDF. Failure leaves the Markdown intact.',
      envTitle: 'Environment',
      envBadge: 'Session check',
      envBody: 'Typst, the CJK fonts and the Typst packages are prepared automatically.',
      envAutoTitle: 'Install Typst automatically',
      envAutoHint: 'Downloads the official release on first use (~20 MB) after SHA256 verification. Off: print install instructions instead.',
      envPathTitle: 'Typst executable',
      envPathHint: 'Leave empty to auto-detect; set an absolute path to pin a version.',
      envPathPlaceholder: 'Empty = auto-detect',
      envMirrorTitle: 'Typst download mirror',
      envMirrorHint: 'Prefix for the GitHub release URL, e.g. https://ghfast.top/.',
      envMirrorPlaceholder: 'https://ghfast.top/',
      envHint: 'Run zju_doctor for actual versions and paths.',
      studyTitle: 'Active recall',
      studyBadge: 'Optional',
      studyTitle2: 'Fill-in study notes',
      studyHint: 'Adds zju_build_study_notes and the scholia-notes Skill.',
      slidesTitle: 'Classroom projection',
      slidesBadge: 'Needs login',
      slidesTitle2: 'Capture projected slides',
      slidesHint: 'Registers zju_fetch_slides. The transcript path is unaffected.',
      imagesTitle: 'Reference screenshots in notes',
      imagesHint: 'Only when capture is on; adds download time and vision tokens.',
      dependency: 'Turn on capture first.',
      loginTitle: 'Login helpers',
      loginBadge: 'On demand',
      loginBody: 'Sign-in is always available: run /zju-lecture-summarizer-login or ask the agent. A separate browser window is used; only the session is stored locally.',
      loginTitle2: 'Video URL and credential tools',
      loginHint: 'Adds zju_get_video_url and zju_read_browser_cookie. zju_login is unaffected.',
      advancedTitle: 'Advanced',
      advancedBadge: 'Rarely needed',
      pythonTitle: 'Python interpreter',
      pythonHint: 'Empty tries the bundled Python, then py -3, python and python3.',
      pythonPlaceholder: 'Empty = auto-detect',
      timeoutTitle: 'Tool timeout (ms)',
      timeoutHint: 'Default 120000. PDF tools use at least 300000; downloads and login at least 600000.',
      registerSkillTitle: 'Register bundled Skills',
      registerSkillHint: 'Off hides the course workflow; tools stay available.',
      toolsNowHint: 'Saved live; no restart required.',
      saveIdle: '',
      saveSaving: 'Saving…',
      saveDone: 'Saved',
      saveFailed: 'Not saved. Try again.',
      loading: 'Loading this setting…',
      unavailable: 'This setting is not available in the current profile.',
      readOnly: 'This deployment stores plugin settings read-only.',
    }

    const zh = {
      sectionTitle: '浙大智云课堂讲义',
      panelLabel: '智云讲义',
      panelNote: '也可在「设置 → 浙大智云课堂讲义」中打开。',
      eyebrow: 'ZJU · 智云课堂',
      heroTitle: '把课程回放整理成可复习的讲义',
      heroBody: '字幕先匿名；401/403 时用本机登录态重试一次。PDF 在本地排版。',
      pipelineTranscript: '字幕',
      pipelineNotes: 'Markdown 讲义',
      pipelinePdf: '阅读 PDF',
      toolCountLabel: '个工具',
      toolsNowPrefix: '当前配置注册',
      toolsNowSuffix: '个工具',
      pdfOn: 'PDF 开',
      pdfOff: 'PDF 关',
      presetsTitle: '一键配置',
      presetToken: '省 Token',
      presetStudy: '复习模式',
      presetFull: '全功能',
      presetTokenHint: '仅 PDF',
      presetStudyHint: 'PDF + 填空笔记',
      presetFullHint: '全部模块',
      coreTitle: '核心链路',
      coreBadge: '始终开启',
      coreRowTitle: '字幕 → 讲义 → 校验',
      coreRowHint: '无需配置。',
      outputTitle: '阅读输出',
      outputBadge: '推荐',
      outputBody: 'Markdown 是源文件，PDF 是阅读版。',
      pdfTitle: '自动排版 PDF',
      pdfHint: '写入讲义后生成同名 PDF；失败不影响 Markdown。',
      envTitle: '环境',
      envBadge: '会话内可查',
      envBody: 'Typst、中文字体与 Typst 包自动准备。',
      envAutoTitle: '自动安装 Typst',
      envAutoHint: '首次使用时下载官方版本（约 20 MB）并校验 SHA256；关闭后只提示安装命令。',
      envPathTitle: 'Typst 可执行文件',
      envPathHint: '留空自动查找；填写绝对路径可固定版本。',
      envPathPlaceholder: '留空 = 自动查找',
      envMirrorTitle: 'Typst 下载镜像',
      envMirrorHint: 'GitHub Release 前缀，例如 https://ghfast.top/。',
      envMirrorPlaceholder: 'https://ghfast.top/',
      envHint: '运行 zju_doctor 查看实际版本与路径。',
      studyTitle: '主动回忆',
      studyBadge: '可选',
      studyTitle2: '填空式学习笔记',
      studyHint: '额外注册 zju_build_study_notes 与 scholia-notes Skill。',
      slidesTitle: '课堂投影',
      slidesBadge: '需登录',
      slidesTitle2: '抓取投影截图',
      slidesHint: '注册 zju_fetch_slides；字幕链路不受影响。',
      imagesTitle: '把截图引用进讲义',
      imagesHint: '仅在投影抓取开启时生效；增加下载时间与视觉 token。',
      dependency: '请先开启投影抓取。',
      loginTitle: '登录辅助',
      loginBadge: '按需',
      loginBody: '登录入口始终可用：输入 /zju-lecture-summarizer-login 或让 Agent 登录。使用独立浏览器窗口，只在本机保存登录态。',
      loginTitle2: '视频直链与登录态工具',
      loginHint: '仅额外注册 zju_get_video_url 与 zju_read_browser_cookie；zju_login 不受影响。',
      advancedTitle: '高级',
      advancedBadge: '按需调整',
      pythonTitle: 'Python 解释器',
      pythonHint: '留空依次尝试自带 Python、py -3、python、python3。',
      pythonPlaceholder: '留空 = 自动查找',
      timeoutTitle: '工具超时（毫秒）',
      timeoutHint: '默认 120000；PDF 工具至少 300000，下载与登录至少 600000。',
      registerSkillTitle: '注册随包 Skill',
      registerSkillHint: '关闭后不加载课程工作流；工具仍可用。',
      toolsNowHint: '保存后立即同步，无需重启。',
      saveIdle: '',
      saveSaving: '正在保存…',
      saveDone: '已保存',
      saveFailed: '未保存，请重试。',
      loading: '正在加载该设置…',
      unavailable: '当前 profile 未提供该设置。',
      readOnly: '本部署的插件设置为只读。',
    }

    const CSS = [
      '.zju-settings-page{display:flex;flex-direction:column;gap:14px;width:100%;max-width:760px;box-sizing:border-box}',
      '.zju-hero{box-sizing:border-box;padding:2px 0 0}',
      '.zju-eyebrow{font-size:11px;line-height:16px;letter-spacing:.16em;color:var(--dsw-alias-brand-primary);font-weight:600}',
      '.zju-hero-title{margin:6px 0 0;font-size:20px;line-height:28px;font-weight:600;color:var(--dsw-alias-label-primary)}',
      '.zju-hero-body{margin:6px 0 0;max-width:54em;font-size:12px;line-height:19px;color:var(--dsw-alias-label-secondary)}',
      '.zju-hero-top{display:flex;align-items:flex-start;justify-content:space-between;gap:16px}',
      '.zju-hero-badges{display:flex;flex-wrap:wrap;gap:6px;justify-content:flex-end;flex:none}',
      '.zju-pill{display:inline-flex;align-items:center;height:22px;padding:0 8px;border:1px solid var(--dsw-alias-border-l2);border-radius:999px;background:transparent;font-size:11px;line-height:20px;color:var(--dsw-alias-label-secondary);white-space:nowrap}',
      '.zju-pill.is-on{border-color:color-mix(in srgb,var(--dsw-alias-brand-primary) 45%,transparent);color:var(--dsw-alias-brand-primary);background:color-mix(in srgb,var(--dsw-alias-brand-primary) 8%,transparent)}',
      '.zju-pipeline{display:flex;align-items:center;gap:7px;flex-wrap:wrap;margin-top:12px}',
      '.zju-step{display:inline-flex;align-items:center;height:26px;padding:0 10px;border-radius:8px;border:1px solid var(--dsw-alias-border-l2);background:transparent;font-size:12px;line-height:24px;color:var(--dsw-alias-label-primary)}',
      '.zju-step.is-off{color:var(--dsw-alias-label-tertiary);border-style:dashed;background:transparent}',
      '.zju-arrow{font-size:12px;line-height:1;color:var(--dsw-alias-label-tertiary)}',
      '.zju-presets{display:flex;align-items:center;gap:8px;flex-wrap:wrap}',
      '.zju-presets-label{font-size:12px;color:var(--dsw-alias-label-secondary);margin-right:2px}',
      '.zju-preset{display:inline-flex;flex-direction:column;align-items:flex-start;gap:1px;padding:6px 10px;border:1px solid var(--dsw-alias-border-l2);border-radius:8px;background:transparent;cursor:pointer;font:inherit;color:var(--dsw-alias-label-primary);text-align:left}',
      '.zju-preset:hover:not(:disabled){border-color:color-mix(in srgb,var(--dsw-alias-brand-primary) 45%,var(--dsw-alias-border-l2));background:color-mix(in srgb,var(--dsw-alias-brand-primary) 5%,transparent)}',
      '.zju-preset:disabled{opacity:.5;cursor:default}',
      '.zju-preset:focus-visible{outline:2px solid var(--dsw-alias-brand-primary);outline-offset:2px}',
      '.zju-preset-name{font-size:12px;line-height:17px;font-weight:500}',
      '.zju-preset-hint{font-size:10px;line-height:14px;color:var(--dsw-alias-label-tertiary)}',
      '.zju-groups{display:flex;flex-direction:column;border-top:1px solid color-mix(in srgb,var(--dsw-alias-label-tertiary) 26%,transparent)}',
      '.zju-group{padding:16px 0 12px}',
      '.zju-group + .zju-group{border-top:1px solid color-mix(in srgb,var(--dsw-alias-label-tertiary) 26%,transparent)}',
      '.zju-group-head{display:flex;align-items:center;justify-content:space-between;gap:10px}',
      '.zju-group-title{margin:0;font-size:13px;line-height:19px;font-weight:600;color:var(--dsw-alias-label-primary)}',
      '.zju-group-body{margin:3px 0 0;font-size:11px;line-height:17px;color:var(--dsw-alias-label-tertiary)}',
      '.zju-group-rows{padding-left:20px;padding-top:2px}',
      '.zju-badge{flex:none;font-size:10px;line-height:15px;padding:0 6px;border-radius:5px;color:var(--dsw-alias-label-secondary);background:var(--dsw-alias-bg-layer-2)}',
      '.zju-row{display:flex;justify-content:space-between;align-items:flex-start;gap:22px;padding:10px 0 0}',
      '.zju-row.is-child{padding-left:20px}',
      '.zju-copy{min-width:0}',
      '.zju-row-title{font-size:13px;line-height:19px;color:var(--dsw-alias-label-primary)}',
      '.zju-row-hint{margin-top:3px;font-size:11px;line-height:17px;color:var(--dsw-alias-label-secondary)}',
      '.zju-field{flex:none;display:flex;align-items:center;gap:6px}',
      '.zju-input{box-sizing:border-box;width:228px;height:30px;padding:0 8px;border:1px solid var(--dsw-alias-border-l2);border-radius:7px;background:var(--dsw-alias-bg-layer-1);color:var(--dsw-alias-label-primary);font:inherit;font-size:12px}',
      '.zju-input::placeholder{color:var(--dsw-alias-label-tertiary)}',
      '.zju-input:focus-visible{outline:2px solid var(--dsw-alias-brand-primary);outline-offset:1px}',
      '.zju-input:disabled{opacity:.45;cursor:default}',
      '@media (max-width:560px){.zju-input{width:100%}.zju-field{width:100%}}',
      '.zju-switch{position:relative;flex:none;width:36px;height:20px;padding:0;border:1px solid var(--dsw-alias-border-l2);border-radius:999px;background:var(--dsw-alias-bg-layer-2);cursor:pointer;transition:background-color .15s ease,border-color .15s ease}',
      '.zju-switch[aria-checked="true"]{background:var(--dsw-alias-brand-primary);border-color:var(--dsw-alias-brand-primary)}',
      '.zju-switch:disabled{opacity:.42;cursor:default}',
      '.zju-switch:focus-visible{outline:2px solid var(--dsw-alias-brand-primary);outline-offset:2px}',
      '.zju-knob{position:absolute;top:2px;left:2px;width:14px;height:14px;border-radius:50%;background:var(--dsw-alias-bg-layer-1);box-shadow:0 1px 2px rgba(0,0,0,.18);transition:left .15s ease}',
      '.zju-switch[aria-checked="true"] .zju-knob{left:18px}',
      '.zju-foot{display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap;padding:0 2px;font-size:11px;line-height:17px;color:var(--dsw-alias-label-secondary)}',
      '.zju-save[data-state="saved"]{color:var(--dsw-alias-state-success-primary)}',
      '.zju-save[data-state="failed"]{color:var(--dsw-alias-state-error-primary)}',
      '.zju-note{font-size:11px;line-height:17px;color:var(--dsw-alias-label-tertiary)}',
      '.zju-panel{box-sizing:border-box;height:100%;overflow:auto;display:flex;justify-content:center;align-items:flex-start;padding:0 clamp(16px,3vw,32px) 40px}',
      '.zju-panel-inner{box-sizing:border-box;width:100%;max-width:760px;padding-top:calc(20px + var(--dsh-frame-top-clearance,0px))}',
      '@media (max-width:560px){.zju-hero-top{flex-direction:column}.zju-hero-badges{justify-content:flex-start}.zju-row{gap:12px}}',
    ].join('\n')

    /**
     * One settings controller, shared by every switch on the page.
     *
     * The Host serves configuration forms only for `Config` fields marked
     * `.volatile()`. The mirror row is found by its namespace or by any known
     * field in its schema, so this page keeps working when the bundle is
     * composed under an `include:` entry id.
     */
    class PipelineSettings {
      constructor(ctx) {
        this.ctx = ctx
        this.listeners = new Set()
        this.namespace = null
        this.form = null
        this.formUnsubscribe = null
        this.mirror = ctx.configForms.describe()
        this.snapshot = {
          status: 'loading',
          value: undefined,
          writable: false,
          revision: undefined,
          error: null,
        }
        this.mirrorUnsubscribe = this.mirror.subscribe(() => this.sync())
        void Promise.resolve(this.mirror.ensure()).catch(() => {})
        this.sync()
      }

      subscribe = (listener) => {
        this.listeners.add(listener)
        return () => this.listeners.delete(listener)
      }

      getSnapshot = () => this.snapshot

      emit() {
        for (const listener of [...this.listeners]) listener()
      }

      publish(snapshot) {
        this.snapshot = snapshot
        this.emit()
      }

      isOurs(row) {
        if (!row || typeof row !== 'object') return false
        if (CANDIDATE_NAMESPACES.includes(row.ns)) return true
        if (typeof row.ns === 'string' && row.ns.includes('zju-lecture')) return true
        const hasField = (value) => value && typeof value === 'object' && 'enableSlides' in value
        if (hasField(row.value) || hasField(row.base)) return true
        try {
          return JSON.stringify(row.schema || '').includes('"enableSlides"')
        } catch {
          return false
        }
      }

      sync() {
        const view = this.mirror.getSnapshot()?.view
        const rows = Array.isArray(view?.namespaces) ? view.namespaces : []
        const row = rows.find((candidate) => this.isOurs(candidate))
        if (!row) {
          this.publish({
            status: view === undefined ? 'loading' : 'unavailable',
            value: undefined,
            writable: false,
            revision: undefined,
            error: null,
          })
          return
        }
        if (row.ns !== this.namespace) {
          this.namespace = row.ns
          this.form = this.ctx.configForms.get(row.ns)
          if (this.formUnsubscribe) this.formUnsubscribe()
          this.formUnsubscribe = this.form.subscribe(() => this.publishForm())
        }
        this.publishForm()
      }

      publishForm() {
        const form = this.form?.getSnapshot()
        this.publish({
          status: form?.status || 'unavailable',
          value: form?.value || {},
          writable: form?.writable === true,
          revision: form?.revision,
          error: this.snapshot.error || null,
        })
      }

      async #writeOne(field, value) {
        if (!this.form) return false
        // `set` is the convenience path used by this plugin since 1.5.1;
        // `mutate` is the lower-level scope API (revision-fenced batch). Try
        // the convenience path first, fall back to one path-addressed op.
        if (typeof this.form.set === 'function') {
          return (await this.form.set(field, value)) !== false
        }
        if (typeof this.form.mutate === 'function') {
          const current = this.form.getSnapshot()
          const accepted = await this.form.mutate(
            [{ op: 'set', path: field, value }],
            current?.revision,
          )
          return accepted !== false
        }
        return false
      }

      async setField(field, value) {
        try {
          const accepted = await this.#writeOne(field, value)
          this.publish({ ...this.snapshot, error: accepted ? null : 'saveFailed' })
          return accepted
        } catch {
          this.publish({ ...this.snapshot, error: 'saveFailed' })
          return false
        }
      }

      /** Write several switches as one user action (preset button). */
      async setFields(entries) {
        // A batch is one revision-fenced write: the Host applies every field
        // or none. Sequential writes could race a plugin reload between them.
        if (this.form && typeof this.form.mutate === 'function') {
          try {
            const current = this.form.getSnapshot()
            const ops = entries.map(([field, value]) => ({ op: 'set', path: field, value }))
            const accepted = await this.form.mutate(ops, current?.revision)
            if (accepted !== false) {
              this.publish({ ...this.snapshot, error: null })
              return true
            }
          } catch {
            /* fall through to the per-field path */
          }
        }
        for (const [field, value] of entries) {
          try {
            const accepted = await this.#writeOne(field, value)
            if (!accepted) {
              this.publish({ ...this.snapshot, error: 'saveFailed' })
              return false
            }
          } catch {
            this.publish({ ...this.snapshot, error: 'saveFailed' })
            return false
          }
        }
        this.publish({ ...this.snapshot, error: null })
        return true
      }

      dispose() {
        this.mirrorUnsubscribe?.()
        this.formUnsubscribe?.()
        this.listeners.clear()
      }
    }

    function Toggle({ checked, disabled, label, onChange }) {
      return h('button', {
        type: 'button',
        role: 'switch',
        'aria-checked': checked ? 'true' : 'false',
        'aria-label': label,
        disabled,
        className: 'zju-switch',
        onClick: () => {
          if (!disabled) onChange(!checked)
        },
      }, h('span', { className: 'zju-knob', 'aria-hidden': 'true' }))
    }

    /**
     * One text or number input for the advanced settings.
     *
     * The field keeps a local draft so typing does not write to the Host on
     * every keystroke; blur or Enter commits one revision-fenced write. A
     * failed write leaves the previous value in the form snapshot, so the
     * effect below resets the draft on the next render.
     */
    function TextField({
      label,
      value,
      placeholder,
      disabled,
      type = 'text',
      min,
      max,
      step,
      onCommit,
    }) {
      const [draft, setDraft] = React.useState(value ?? '')
      React.useEffect(() => {
        setDraft(value ?? '')
      }, [value])
      const commit = () => {
        const text = String(draft).trim()
        if (type === 'number') {
          const number = Number(text)
          if (!text || !Number.isFinite(number)) {
            setDraft(value ?? '')
            return
          }
          const clamped = Math.min(Number(max), Math.max(Number(min), Math.round(number)))
          if (clamped !== Number(value)) onCommit(clamped)
          else setDraft(String(value ?? ''))
          return
        }
        if (text !== String(value ?? '')) onCommit(text)
      }
      return h('input', {
        type,
        className: 'zju-input',
        value: draft,
        placeholder,
        disabled,
        'aria-label': label,
        min,
        max,
        step,
        onChange: (event) => setDraft(event.target.value),
        onBlur: commit,
        onKeyDown: (event) => {
          if (event.key === 'Enter') event.currentTarget.blur()
        },
      })
    }

    function useSettingsSnapshot(settings) {
      const [snapshot, setSnapshot] = React.useState(settings.getSnapshot())
      React.useEffect(() => {
        setSnapshot(settings.getSnapshot())
        return settings.subscribe(() => setSnapshot(settings.getSnapshot()))
      }, [settings])
      return snapshot
    }

    function useSaveState() {
      const [state, setState] = React.useState('idle')
      const run = async (action) => {
        setState('saving')
        const ok = await action()
        setState(ok ? 'saved' : 'failed')
        return ok
      }
      return [state, run]
    }

    function Row({ t, title, hint, checked, disabled, onChange }) {
      return h('div', { className: 'zju-row' },
        h('div', { className: 'zju-copy' },
          h('div', { className: 'zju-row-title' }, t(title)),
          h('div', { className: 'zju-row-hint' }, t(hint)),
        ),
        h(Toggle, { checked, disabled, label: t(title), onChange }),
      )
    }

    function InputRow({
      t,
      title,
      hint,
      value,
      placeholder,
      type,
      min,
      max,
      step,
      disabled,
      onCommit,
    }) {
      return h('div', { className: 'zju-row' },
        h('div', { className: 'zju-copy' },
          h('div', { className: 'zju-row-title' }, t(title)),
          h('div', { className: 'zju-row-hint' }, t(hint)),
        ),
        h('div', { className: 'zju-field' },
          h(TextField, {
            label: t(title),
            value,
            placeholder,
            type,
            min,
            max,
            step,
            disabled,
            onCommit,
          }),
        ),
      )
    }

    function Group({ title, body, badge, children }) {
      return h('section', { className: 'zju-group' },
        h('header', { className: 'zju-group-head' },
          h('h3', { className: 'zju-group-title' }, title),
          badge ? h('span', { className: 'zju-badge' }, badge) : null,
        ),
        body ? h('p', { className: 'zju-group-body' }, body) : null,
        h('div', { className: 'zju-group-rows' }, children),
      )
    }

    function PipelineSection({ t, settings, asPage }) {
      const snapshot = useSettingsSnapshot(settings)
      const [saveState, runSave] = useSaveState()
      const value = snapshot.value || {}
      const enableSlides = value.enableSlides === true
      const renderPdf = value.renderPdf !== false
      const typstAutoInstall = value.typstAutoInstall !== false
      const enableStudyNotes = value.enableStudyNotes === true
      const enableLoginTools = value.enableLoginTools === true
      const embedSlideImages = enableSlides && value.embedSlideImages === true
      const registerSkill = value.registerSkill !== false
      const python = typeof value.python === 'string' ? value.python : ''
      const typstPath = typeof value.typstPath === 'string' ? value.typstPath : ''
      const typstMirror = typeof value.typstMirror === 'string' ? value.typstMirror : ''
      const timeoutMs = Number.isFinite(value.timeoutMs) ? value.timeoutMs : 120000
      const ready = snapshot.status === 'ready'
      const disabled = !ready || !snapshot.writable || saveState === 'saving'
      const toolCount = 7
        + (enableStudyNotes ? 1 : 0)
        + (enableSlides ? 1 : 0)
        + (enableLoginTools ? 2 : 0)
      const note = !ready && snapshot.status !== 'unavailable'
        ? t('loading')
        : snapshot.status === 'unavailable'
          ? t('unavailable')
          : ready && !snapshot.writable
            ? t('readOnly')
            : null
      const saveLabel = saveState === 'saving'
        ? t('saveSaving')
        : saveState === 'saved'
          ? t('saveDone')
          : saveState === 'failed'
            ? t('saveFailed')
            : snapshot.error
              ? t('saveFailed')
              : ''

      const update = (field, next) => runSave(() => settings.setField(field, next))

      const applyPreset = (preset) => runSave(async () => {
        const sets = preset === 'token'
          ? [['renderPdf', true], ['enableStudyNotes', false], ['enableSlides', false], ['embedSlideImages', false], ['enableLoginTools', false]]
          : preset === 'study'
            ? [['renderPdf', true], ['enableStudyNotes', true], ['enableSlides', false], ['embedSlideImages', false], ['enableLoginTools', false]]
            : [['renderPdf', true], ['enableStudyNotes', true], ['enableSlides', true], ['embedSlideImages', true], ['enableLoginTools', true]]
        return settings.setFields(sets)
      })

      return h('div', { className: 'zju-settings-page', 'data-zju-settings': 'pipeline' },
        h('style', { 'data-plugin': '@plugin/dsh-zju-lecture-note' }, CSS),
        h('header', { className: 'zju-hero' },
          h('div', { className: 'zju-hero-top' },
            h('div', null,
              h('div', { className: 'zju-eyebrow' }, t('eyebrow')),
              h(asPage ? 'h1' : 'h2', { className: 'zju-hero-title' }, t('heroTitle')),
              h('p', { className: 'zju-hero-body' }, t('heroBody')),
            ),
            h('div', { className: 'zju-hero-badges' },
              h('span', { className: 'zju-pill' }, `${toolCount} ${t('toolCountLabel')}`),
              h('span', { className: `zju-pill${renderPdf ? ' is-on' : ''}` }, renderPdf ? t('pdfOn') : t('pdfOff')),
            ),
          ),
          h('div', { className: 'zju-pipeline', 'aria-hidden': 'true' },
            h('span', { className: 'zju-step' }, t('pipelineTranscript')),
            h('span', { className: 'zju-arrow' }, '→'),
            h('span', { className: 'zju-step' }, t('pipelineNotes')),
            h('span', { className: 'zju-arrow' }, '→'),
            h('span', { className: `zju-step${renderPdf ? '' : ' is-off'}` }, t('pipelinePdf')),
          ),
        ),
        note ? h('div', { className: 'zju-note', role: 'status' }, note) : null,
        h('div', { className: 'zju-presets' },
          h('span', { className: 'zju-presets-label' }, t('presetsTitle')),
          h('button', { type: 'button', className: 'zju-preset', disabled, onClick: () => applyPreset('token') },
            h('span', { className: 'zju-preset-name' }, t('presetToken')),
            h('span', { className: 'zju-preset-hint' }, t('presetTokenHint')),
          ),
          h('button', { type: 'button', className: 'zju-preset', disabled, onClick: () => applyPreset('study') },
            h('span', { className: 'zju-preset-name' }, t('presetStudy')),
            h('span', { className: 'zju-preset-hint' }, t('presetStudyHint')),
          ),
          h('button', { type: 'button', className: 'zju-preset', disabled, onClick: () => applyPreset('full') },
            h('span', { className: 'zju-preset-name' }, t('presetFull')),
            h('span', { className: 'zju-preset-hint' }, t('presetFullHint')),
          ),
        ),
        h('div', { className: 'zju-groups' },
          h(Group, {
            title: t('coreTitle'),
            badge: t('coreBadge'),
          },
            h(Row, {
              t,
              title: 'coreRowTitle',
              hint: 'coreRowHint',
              checked: true,
              disabled: true,
              onChange: () => {},
            }),
          ),
          h(Group, {
            title: t('outputTitle'),
            body: t('outputBody'),
            badge: t('outputBadge'),
          },
            h(Row, {
              t,
              title: 'pdfTitle',
              hint: 'pdfHint',
              checked: renderPdf,
              disabled,
              onChange: (next) => update('renderPdf', next),
            }),
          ),
          h(Group, {
            title: t('envTitle'),
            body: t('envBody'),
            badge: t('envBadge'),
          },
            h(Row, {
              t,
              title: 'envAutoTitle',
              hint: 'envAutoHint',
              checked: typstAutoInstall,
              disabled,
              onChange: (next) => update('typstAutoInstall', next),
            }),
            h(InputRow, {
              t,
              title: 'envPathTitle',
              hint: 'envPathHint',
              value: typstPath,
              placeholder: t('envPathPlaceholder'),
              disabled,
              onCommit: (next) => update('typstPath', next),
            }),
            h(InputRow, {
              t,
              title: 'envMirrorTitle',
              hint: 'envMirrorHint',
              value: typstMirror,
              placeholder: t('envMirrorPlaceholder'),
              disabled,
              onCommit: (next) => update('typstMirror', next),
            }),
            h('div', { className: 'zju-row is-child' },
              h('div', { className: 'zju-copy' },
                h('div', { className: 'zju-row-hint' }, t('envHint')),
              ),
            ),
          ),
          h(Group, {
            title: t('studyTitle'),
            badge: t('studyBadge'),
          },
            h(Row, {
              t,
              title: 'studyTitle2',
              hint: 'studyHint',
              checked: enableStudyNotes,
              disabled,
              onChange: (next) => update('enableStudyNotes', next),
            }),
          ),
          h(Group, {
            title: t('slidesTitle'),
            badge: t('slidesBadge'),
          },
            h(Row, {
              t,
              title: 'slidesTitle2',
              hint: 'slidesHint',
              checked: enableSlides,
              disabled,
              onChange: (next) => update('enableSlides', next),
            }),
            h('div', { className: 'zju-row is-child' },
              h('div', { className: 'zju-copy' },
                h('div', { className: 'zju-row-title' }, t('imagesTitle')),
                h('div', { className: 'zju-row-hint' }, enableSlides ? t('imagesHint') : t('dependency')),
              ),
              h(Toggle, {
                checked: embedSlideImages,
                disabled: disabled || !enableSlides,
                label: t('imagesTitle'),
                onChange: (next) => update('embedSlideImages', next),
              }),
            ),
          ),
          h(Group, {
            title: t('loginTitle'),
            body: t('loginBody'),
            badge: t('loginBadge'),
          },
            h(Row, {
              t,
              title: 'loginTitle2',
              hint: 'loginHint',
              checked: enableLoginTools,
              disabled,
              onChange: (next) => update('enableLoginTools', next),
            }),
          ),
          h(Group, {
            title: t('advancedTitle'),
            badge: t('advancedBadge'),
          },
            h(InputRow, {
              t,
              title: 'pythonTitle',
              hint: 'pythonHint',
              value: python,
              placeholder: t('pythonPlaceholder'),
              disabled,
              onCommit: (next) => update('python', next),
            }),
            h(InputRow, {
              t,
              title: 'timeoutTitle',
              hint: 'timeoutHint',
              value: timeoutMs,
              type: 'number',
              min: 1000,
              max: 900000,
              step: 1000,
              disabled,
              onCommit: (next) => update('timeoutMs', next),
            }),
            h(Row, {
              t,
              title: 'registerSkillTitle',
              hint: 'registerSkillHint',
              checked: registerSkill,
              disabled,
              onChange: (next) => update('registerSkill', next),
            }),
          ),
        ),
        h('footer', { className: 'zju-foot' },
          h('span', { className: 'zju-note' }, `${t('toolsNowPrefix')} ${toolCount} ${t('toolsNowSuffix')} · ${t('toolsNowHint')}`),
          h('span', {
            className: 'zju-save',
            'data-state': saveState,
            'aria-live': 'polite',
          }, saveLabel),
        ),
        asPage ? h('p', { className: 'zju-note' }, t('panelNote')) : null,
      )
    }

    /**
     * The left-column row's glyph. A `sidebar.panellist` entry draws its own
     * icon — the slot hands it `size` and `active`, no icon field exists — and
     * the row's own colour must come through, hence `currentColor`.
     */
    function PanelIcon({ size = 18 }) {
      return h('svg', {
        width: size,
        height: size,
        viewBox: '0 0 20 20',
        fill: 'none',
        stroke: 'currentColor',
        strokeWidth: 1.5,
        strokeLinecap: 'round',
        strokeLinejoin: 'round',
        'aria-hidden': 'true',
        focusable: 'false',
      },
        h('path', { d: 'M4.6 3.4h6.1l4.7 4.7v7.5a1 1 0 0 1-1 1H4.6a1 1 0 0 1-1-1V4.4a1 1 0 0 1 1-1Z' }),
        h('path', { d: 'M10.6 3.5v4.7h4.7' }),
        h('path', { d: 'M6.7 11.2h4.4' }),
        h('path', { d: 'M6.7 13.7h6.2' }),
      )
    }

    /**
     * The page behind the left-column row.
     *
     * A `main` occupant is a full-height centre column, so it owns the page
     * padding the shipped entry pages use: `--dsh-frame-top-clearance` keeps the
     * first row below the window caption on Windows and under the traffic lights
     * on macOS. The content itself is the settings section, unchanged.
     */
    function SettingsPanelPage(props) {
      return h('div', { className: 'zju-panel', 'data-zju-panel': PANEL_ID },
        h('div', { className: 'zju-panel-inner' },
          h(PipelineSection, { ...props, asPage: true }),
        ),
      )
    }

    function apply(ctx) {
      ctx.effect(() => ctx.locale.register(NS, { en, zh }), 'zju-lecture: settings dictionaries')
      const t = ctx.locale.bind(NS)
      const settings = new PipelineSettings(ctx)
      ctx.effect(() => () => settings.dispose(), 'zju-lecture: settings form')
      ctx.effect(() => ctx.slots.inject('settings.section', () => ctx.slots.register({
        name: 'settings.section',
        id: PANEL_ID,
        order: 25,
        label: () => t('sectionTitle'),
        locale: NS,
        inject: () => ({ settings }),
      }, PipelineSection)), 'zju-lecture: settings section')
      // The left column: one `sidebar.panellist` row and the `main` page under
      // the same id. Registered from the inner callback so the row and its page
      // appear together or not at all, exactly as the shipped panels do.
      ctx.effect(() => ctx.slots.inject('main', () => ctx.slots.inject('sidebar.panellist', () => {
        const stopPage = ctx.slots.register({
          name: 'main',
          key: PANEL_ID,
          locale: NS,
          inject: () => ({ settings }),
        }, SettingsPanelPage)
        const stopRow = ctx.slots.register({
          name: 'sidebar.panellist',
          id: PANEL_ID,
          order: 30,
          label: () => t('panelLabel'),
          locale: NS,
        }, PanelIcon)
        return () => {
          stopRow()
          stopPage()
        }
      })), 'zju-lecture: sidebar entry')
    }

    return {
      inject: ['slots', 'locale', 'configForms'],
      apply,
    }
  },
})

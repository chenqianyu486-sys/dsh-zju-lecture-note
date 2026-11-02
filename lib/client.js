/**
 * Browser half of dsh-zju-lecture-note.
 *
 * The Host `Config` is not rendered automatically by dsh: a plugin that wants
 * a configuration UI contributes one. This module adds a single row to
 * Settings → General with the two projection switches:
 *
 *   - `enableSlides`      — register zju_fetch_slides / load the slide pipeline
 *   - `embedSlideImages`  — reference downloaded screenshots in the note
 *
 * It talks to the Host through the shared `configForms` service, so writes
 * carry the current revision and are refused rather than clobbering a newer
 * value. Plain JavaScript, React from the host module table, no build step.
 */

window.__ModuleLoader__.load({
  id: 'dsh-zju-lecture-note',
  factory(require) {
    const React = require('react')
    const h = React.createElement

    const NS = 'dsh-zju-lecture-note'
    const CANDIDATE_NAMESPACES = [
      'include:dsh-zju-lecture-note',
      'dsh-zju-lecture-note',
    ]

    const en = {
      title: 'ZJU classroom lecture notes',
      description:
        'The transcript pipeline is public and needs no login. Projection capture is an optional module and is off by default.',
      slidesTitle: 'Capture projected slides',
      slidesHint:
        'Registers zju_fetch_slides and downloads projection screenshots. Needs a ZJU login session.',
      imagesTitle: 'Reference screenshots in notes',
      imagesHint:
        'Only applies while projection capture is on. Adds download time and vision tokens.',
      loading: 'Loading this setting…',
      unavailable: 'This setting is not available in the current profile.',
      readOnly: 'The deployment stores plugin settings read-only.',
      saveFailed: 'The change was not saved. Try again.',
      on: 'On',
      off: 'Off',
    }

    const zh = {
      title: '浙大智云课堂讲义',
      description:
        '字幕主链路公开免登录；PPT 投影抓取是可选模块，默认关闭。',
      slidesTitle: '启用 PPT 投影抓取',
      slidesHint:
        '开启后注册 zju_fetch_slides 并下载投影截图；需要浙大登录态。',
      imagesTitle: '把截图引用进讲义',
      imagesHint:
        '仅在投影抓取开启时生效；会增加下载时间与视觉 token。',
      loading: '正在加载该设置…',
      unavailable: '当前 profile 未提供该设置。',
      readOnly: '本部署的插件设置为只读。',
      saveFailed: '修改未保存，请重试。',
      on: '开',
      off: '关',
    }

    const CSS = [
      '.zju-settings-row{display:flex;justify-content:space-between;align-items:flex-start;gap:24px;padding:16px 0;border-bottom:.5px solid var(--dsw-alias-border-l2)}',
      '.zju-settings-copy{min-width:0}',
      '.zju-settings-title{font-size:14px;line-height:20px;color:var(--dsw-alias-label-primary)}',
      '.zju-settings-description{margin-top:4px;font-size:12px;line-height:18px;color:var(--dsw-alias-label-secondary)}',
      '.zju-settings-hint{margin-top:4px;font-size:12px;line-height:18px;color:var(--dsw-alias-label-secondary)}',
      '.zju-settings-error{margin-top:4px;font-size:12px;line-height:18px;color:var(--dsw-alias-state-error-primary)}',
      '.zju-settings-controls{display:flex;flex-direction:column;align-items:flex-end;gap:10px;flex:none}',
      '.zju-settings-toggle-row{display:flex;align-items:center;gap:8px;font-size:12px;line-height:18px;color:var(--dsw-alias-label-secondary)}',
      '.zju-settings-toggle-row.is-muted{opacity:.55}',
      '.zju-settings-toggle-label{white-space:nowrap}',
      '.zju-settings-switch{position:relative;width:36px;height:20px;padding:0;border:1px solid var(--dsw-alias-border-l2);border-radius:999px;background:var(--dsw-alias-bg-layer-2);cursor:pointer;transition:background-color .15s ease,border-color .15s ease}',
      '.zju-settings-switch[aria-checked="true"]{background:var(--dsw-alias-brand-primary);border-color:var(--dsw-alias-brand-primary)}',
      '.zju-settings-switch:disabled{opacity:.45;cursor:default}',
      '.zju-settings-switch:focus-visible{outline:2px solid var(--dsw-alias-brand-primary);outline-offset:2px}',
      '.zju-settings-knob{position:absolute;top:2px;left:2px;width:14px;height:14px;border-radius:50%;background:var(--dsw-alias-bg-layer-1);box-shadow:0 1px 2px rgba(0,0,0,.18);transition:left .15s ease}',
      '.zju-settings-switch[aria-checked="true"] .zju-settings-knob{left:18px}',
    ].join('\n')

    /**
     * One projection setting, derived from the shared settings mirror.
     *
     * The Host serves configuration forms only for `Config` fields marked
     * `.volatile()`. The mirror row is found by its namespace or by the
     * `enableSlides` field in its schema, so this page keeps working when the
     * bundle is composed under an `include:` entry id.
     */
    class ProjectionSettings {
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

      async setField(field, value) {
        if (!this.form) return false
        try {
          const accepted = await this.form.set(field, value)
          if (accepted) {
            this.publish({ ...this.snapshot, error: null })
          } else {
            this.publish({ ...this.snapshot, error: 'saveFailed' })
          }
          return accepted
        } catch {
          this.publish({ ...this.snapshot, error: 'saveFailed' })
          return false
        }
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
        className: 'zju-settings-switch',
        onClick: () => {
          if (!disabled) onChange(!checked)
        },
      }, h('span', { className: 'zju-settings-knob', 'aria-hidden': 'true' }))
    }

    function useSettingsSnapshot(settings) {
      const [snapshot, setSnapshot] = React.useState(settings.getSnapshot())
      React.useEffect(() => {
        setSnapshot(settings.getSnapshot())
        return settings.subscribe(() => setSnapshot(settings.getSnapshot()))
      }, [settings])
      return snapshot
    }

    function ProjectionRow({ t, settings }) {
      const snapshot = useSettingsSnapshot(settings)
      const [busy, setBusy] = React.useState(false)
      const value = snapshot.value || {}
      const enableSlides = value.enableSlides === true
      const embedSlideImages = value.embedSlideImages === true
      const ready = snapshot.status === 'ready'
      const disabled = !ready || !snapshot.writable || busy
      const update = async (field, next) => {
        if (disabled) return
        setBusy(true)
        await settings.setField(field, next)
        setBusy(false)
      }

      return h('div', { className: 'zju-settings-row', 'data-zju-settings': 'projection' },
        h('style', { 'data-plugin': '@plugin/dsh-zju-lecture-note' }, CSS),
        h('div', { className: 'zju-settings-copy' },
          h('div', { className: 'zju-settings-title' }, t('title')),
          h('div', { className: 'zju-settings-description' }, t('description')),
          !ready && snapshot.status !== 'unavailable'
            ? h('div', { className: 'zju-settings-hint' }, t('loading'))
            : null,
          snapshot.status === 'unavailable'
            ? h('div', { className: 'zju-settings-hint' }, t('unavailable'))
            : null,
          ready && !snapshot.writable
            ? h('div', { className: 'zju-settings-hint' }, t('readOnly'))
            : null,
          snapshot.error
            ? h('div', { className: 'zju-settings-error', role: 'status' }, t(snapshot.error))
            : null,
        ),
        h('div', { className: 'zju-settings-controls' },
          h('div', { className: 'zju-settings-toggle-row' },
            h('span', { className: 'zju-settings-toggle-label' }, t('slidesTitle')),
            h(Toggle, {
              checked: enableSlides,
              disabled,
              label: t('slidesTitle'),
              onChange: (next) => update('enableSlides', next),
            }),
          ),
          h('div', { className: `zju-settings-toggle-row${enableSlides ? '' : ' is-muted'}` },
            h('span', { className: 'zju-settings-toggle-label' }, t('imagesTitle')),
            h(Toggle, {
              checked: embedSlideImages,
              disabled: disabled || !enableSlides,
              label: t('imagesTitle'),
              onChange: (next) => update('embedSlideImages', next),
            }),
          ),
        ),
      )
    }

    function apply(ctx) {
      ctx.effect(() => ctx.locale.register(NS, { en, zh }), 'zju-lecture: settings dictionaries')
      const settings = new ProjectionSettings(ctx)
      ctx.effect(() => () => settings.dispose(), 'zju-lecture: settings form')
      ctx.effect(() => ctx.slots.inject('settings.general.item', () => ctx.slots.register({
        name: 'settings.general.item',
        id: NS,
        order: 95,
        locale: NS,
        inject: () => ({ settings }),
      }, ProjectionRow)), 'zju-lecture: settings row')
    }

    return {
      inject: ['slots', 'locale', 'configForms'],
      apply,
    }
  },
})

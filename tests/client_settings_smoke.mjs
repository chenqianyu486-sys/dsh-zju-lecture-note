/**
 * Smoke test for the browser half of dsh-zju-lecture-note.
 *
 * Loads `lib/client.js` under a fake module loader, then exercises the
 * settings row registration against fake `slots` / `locale` / `configForms`
 * services. No browser, no React renderer, no DSH page required.
 *
 * Usage: node tests/client_settings_smoke.mjs
 * Output: one JSON line, e.g. {"ok":true,"slot":"settings.general.item",...}
 */

let definition

globalThis.window = {
  __ModuleLoader__: {
    load(value) {
      definition = value
    },
  },
}

await import('../lib/client.js')

if (!definition || definition.id !== 'dsh-zju-lecture-note') {
  throw new Error(`unexpected client id: ${definition?.id ?? 'undefined'}`)
}

const react = {
  createElement: (type, props, ...children) => ({ type, props, children }),
  useEffect: (effect) => effect(),
  useState: (initial) => [initial, () => {}],
}

const module = definition.factory((specifier) => {
  if (specifier === 'react') return react
  throw new Error(`unexpected require: ${specifier}`)
})

const registered = []
const formCalls = []
const formState = {
  status: 'ready',
  value: { enableSlides: false, embedSlideImages: false },
  writable: true,
  revision: 7,
}
const form = {
  getSnapshot: () => formState,
  subscribe: () => () => {},
  set: async (field, value) => {
    formCalls.push([field, value])
    formState.value = { ...formState.value, [field]: value }
    return true
  },
}
const mirror = {
  getSnapshot: () => ({
    status: 'ready',
    view: {
      namespaces: [{
        ns: 'include:dsh-zju-lecture-note',
        schema: { properties: { enableSlides: { type: 'boolean' }, embedSlideImages: { type: 'boolean' } } },
        value: { enableSlides: false, embedSlideImages: false },
        revision: 7,
      }],
    },
  }),
  subscribe: () => () => {},
  ensure: () => Promise.resolve(),
}

const ctx = {
  effect: (callback) => callback(),
  locale: {
    register: (...args) => {
      registered.push({ kind: 'locale', args })
      return () => {}
    },
    bind: () => (key) => key,
  },
  slots: {
    inject: (_slot, callback) => callback(),
    register: (registration, component) => {
      registered.push({ kind: 'slot', registration, component })
      return () => {}
    },
  },
  configForms: {
    describe: () => mirror,
    get: (namespace) => {
      if (namespace !== 'include:dsh-zju-lecture-note') throw new Error(`unexpected namespace: ${namespace}`)
      return form
    },
  },
}

module.apply(ctx)

const slotEntries = registered.filter((entry) => entry.kind === 'slot')
const slotByName = (name) => slotEntries.find((entry) => entry.registration.name === name)

const settingsSlot = slotByName('settings.section')
if (!settingsSlot) throw new Error('settings.section was not registered')
if (settingsSlot.registration.name !== 'settings.section') throw new Error('wrong slot name')
if (settingsSlot.registration.id !== 'zju-lecture') throw new Error('wrong settings section id')
if (settingsSlot.registration.order !== 25) throw new Error('wrong settings section order')
if (typeof settingsSlot.registration.label !== 'function') throw new Error('settings section label must be localized')
if (typeof settingsSlot.registration.locale !== 'string') throw new Error('settings section has no locale')

// The left column: one rail row and the global panel it opens, under one id.
const panelSlot = slotByName('main')
if (!panelSlot) throw new Error('the main panel behind the sidebar row was not registered')
if (panelSlot.registration.key !== 'zju-lecture') throw new Error('wrong main panel key')
if (panelSlot.registration.key !== settingsSlot.registration.id) {
  throw new Error('the sidebar row and its panel must share one id')
}
if (typeof panelSlot.registration.locale !== 'string') throw new Error('the panel has no locale')

const rowSlot = slotByName('sidebar.panellist')
if (!rowSlot) throw new Error('the sidebar.panellist row was not registered')
if (rowSlot.registration.id !== panelSlot.registration.key) throw new Error('row id and panel key must agree')
if (rowSlot.registration.order !== 30) throw new Error('wrong sidebar row order')
if (typeof rowSlot.registration.label !== 'function') throw new Error('the sidebar row label must be localized')
if (rowSlot.registration.label() !== 'panelLabel') throw new Error('the sidebar row label must come from the dictionary')

const icon = rowSlot.component({ size: 18, active: false })
if (icon.type !== 'svg') throw new Error('the sidebar row must draw its own svg glyph')
if (!icon.props || !icon.props['aria-hidden']) throw new Error('the glyph must be hidden from assistive tech')

const face = settingsSlot.registration.inject()
if (!face || !face.settings) throw new Error('settings row inject face is missing the controller')

const panelFace = panelSlot.registration.inject()
if (!panelFace || panelFace.settings !== face.settings) {
  throw new Error('the panel must reuse the settings controller, not open a second one')
}
const page = panelSlot.component({ t: (key) => key, ...panelFace })
if (!page || page.type !== 'div' || page.props?.className !== 'zju-panel') {
  throw new Error('the panel did not render its page shell')
}

const initial = face.settings.getSnapshot()
if (initial.status !== 'ready') throw new Error(`unexpected initial status: ${initial.status}`)
if (initial.writable !== true) throw new Error('initial form is not writable')
if (initial.value?.enableSlides !== false) throw new Error('unexpected enableSlides default')

const rendered = settingsSlot.component({ t: (key) => key, settings: face.settings })
if (!rendered || rendered.type !== 'div') throw new Error('settings row component did not render a root div')

const accepted = await face.settings.setField('enableSlides', true)
if (accepted !== true) throw new Error('setField did not report acceptance')
if (formCalls.length !== 1 || formCalls[0][0] !== 'enableSlides' || formCalls[0][1] !== true) {
  throw new Error(`unexpected form calls: ${JSON.stringify(formCalls)}`)
}
face.settings.sync()
if (face.settings.getSnapshot().value?.enableSlides !== true) {
  throw new Error('settings controller did not pick up the written value')
}

process.stdout.write(`${JSON.stringify({
  ok: true,
  id: definition.id,
  services: module.inject,
  slot: settingsSlot.registration.name,
  rowId: settingsSlot.registration.id,
  order: settingsSlot.registration.order,
  panelKey: panelSlot.registration.key,
  sidebarRow: rowSlot.registration.id,
  sidebarOrder: rowSlot.registration.order,
  slots: slotEntries.map((entry) => entry.registration.name),
  calls: formCalls,
  writable: initial.writable,
})}\n`)

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
  value: {
    enableSlides: false,
    slidesAsSource: false,
    embedSlideImages: false,
    renderPdf: true,
    enableStudyNotes: false,
    enableLoginTools: false,
    typstAutoInstall: true,
    typstPath: '',
    typstMirror: '',
    python: '',
    timeoutMs: 120000,
    registerSkill: true,
  },
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
        schema: {
          properties: {
            enableSlides: { type: 'boolean' },
            slidesAsSource: { type: 'boolean' },
            embedSlideImages: { type: 'boolean' },
            renderPdf: { type: 'boolean' },
            enableStudyNotes: { type: 'boolean' },
            enableLoginTools: { type: 'boolean' },
            typstAutoInstall: { type: 'boolean' },
            typstPath: { type: 'string' },
            typstMirror: { type: 'string' },
            python: { type: 'string' },
            timeoutMs: { type: 'number' },
            registerSkill: { type: 'boolean' },
          },
        },
        value: {
          enableSlides: false,
          slidesAsSource: false,
          embedSlideImages: false,
          renderPdf: true,
          enableStudyNotes: false,
          enableLoginTools: false,
          typstAutoInstall: true,
          typstPath: '',
          typstMirror: '',
          python: '',
          timeoutMs: 120000,
          registerSkill: true,
        },
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

/** Flatten the fake React tree into a node list. */
function collectNodes(node, out = []) {
  if (!node || typeof node !== 'object') return out
  if (Array.isArray(node)) {
    for (const child of node) collectNodes(child, out)
    return out
  }
  out.push(node)
  collectNodes(node.children, out)
  return out
}

function presetButtons(tree) {
  return collectNodes(tree).filter((node) => (
    node.type === 'button'
    && String(node.props?.className ?? '').split(' ').includes('zju-preset')
  ))
}

function activePresetId(tree) {
  const active = presetButtons(tree).filter((node) => (
    String(node.props?.className ?? '').split(' ').includes('is-active')
  ))
  if (active.length > 1) {
    throw new Error(`more than one preset is highlighted: ${active.map((node) => node.props['data-preset'])}`)
  }
  return active[0]?.props?.['data-preset'] ?? null
}

const initialPresets = presetButtons(rendered)
const initialPresetIds = initialPresets.map((node) => node.props?.['data-preset'])
if (JSON.stringify(initialPresetIds) !== JSON.stringify(['token', 'study', 'slides', 'full'])) {
  throw new Error(`unexpected preset buttons: ${JSON.stringify(initialPresetIds)}`)
}
if (activePresetId(rendered) !== 'token') {
  throw new Error(`the default config should highlight the token preset, got ${activePresetId(rendered)}`)
}
for (const node of initialPresets) {
  if (node.props?.['aria-pressed'] !== (activePresetId(rendered) === node.props?.['data-preset'] ? 'true' : 'false')) {
    throw new Error(`aria-pressed does not match the highlight for ${node.props?.['data-preset']}`)
  }
}

const accepted = await face.settings.setField('enableSlides', true)
if (accepted !== true) throw new Error('setField did not report acceptance')
if (formCalls.length !== 1 || formCalls[0][0] !== 'enableSlides' || formCalls[0][1] !== true) {
  throw new Error(`unexpected form calls: ${JSON.stringify(formCalls)}`)
}
face.settings.sync()
if (face.settings.getSnapshot().value?.enableSlides !== true) {
  throw new Error('settings controller did not pick up the written value')
}

// The advanced fields use the same controller, but carry strings / numbers
// instead of booleans. A form that only accepted booleans would silently drop
// the value on the floor.
for (const [field, value] of [
  ['timeoutMs', 90000],
  ['python', 'C:\\Python\\python.exe'],
  ['typstPath', 'C:\\typst\\typst.exe'],
  ['typstMirror', 'https://ghfast.top/'],
  ['registerSkill', false],
]) {
  const ok = await face.settings.setField(field, value)
  if (!ok) throw new Error(`setField rejected ${field}`)
  face.settings.sync()
  if (face.settings.getSnapshot().value?.[field] !== value) {
    throw new Error(`settings controller did not keep ${field}=${value}`)
  }
}
const inputCalls = formCalls.slice(1)
if (inputCalls.length !== 5) throw new Error(`advanced writes were not forwarded: ${JSON.stringify(formCalls)}`)

// A preset is only a bulk write over the same switches: all four presets must
// write every module field, and the highlight must follow the resulting config
// (not a stored "selected preset" flag).
const manualCalls = formCalls.slice()
const presetExpectations = {
  token: {
    renderPdf: true,
    enableStudyNotes: false,
    enableSlides: false,
    slidesAsSource: false,
    embedSlideImages: false,
    enableLoginTools: false,
  },
  study: {
    renderPdf: true,
    enableStudyNotes: true,
    enableSlides: false,
    slidesAsSource: false,
    embedSlideImages: false,
    enableLoginTools: false,
  },
  slides: {
    renderPdf: true,
    enableStudyNotes: false,
    enableSlides: true,
    slidesAsSource: true,
    embedSlideImages: true,
    enableLoginTools: false,
  },
  full: {
    renderPdf: true,
    enableStudyNotes: true,
    enableSlides: true,
    slidesAsSource: true,
    embedSlideImages: true,
    enableLoginTools: true,
  },
}
const presetCalls = []
for (const [id, expected] of Object.entries(presetExpectations)) {
  const tree = settingsSlot.component({ t: (key) => key, settings: face.settings })
  const button = presetButtons(tree).find((node) => node.props?.['data-preset'] === id)
  if (!button) throw new Error(`missing preset button: ${id}`)
  const before = formCalls.length
  const ok = await button.props.onClick()
  if (ok !== true) throw new Error(`preset ${id} did not report success`)
  face.settings.sync()
  const calls = formCalls.slice(before)
  presetCalls.push(...calls)
  if (calls.length !== Object.keys(expected).length) {
    throw new Error(`preset ${id} wrote ${calls.length} fields: ${JSON.stringify(calls)}`)
  }
  const written = Object.fromEntries(calls)
  for (const [field, value] of Object.entries(expected)) {
    if (written[field] !== value) {
      throw new Error(`preset ${id} wrote ${field}=${written[field]}, expected ${value}`)
    }
  }
  const active = activePresetId(settingsSlot.component({ t: (key) => key, settings: face.settings }))
  if (active !== id) throw new Error(`preset ${id} did not highlight itself, got ${active}`)
}

// Selecting a preset and setting the same switches by hand must be
// indistinguishable: no hidden selection state, only the config comparison.
formState.value = {
  ...formState.value,
  renderPdf: true,
  enableStudyNotes: false,
  enableSlides: true,
  slidesAsSource: true,
  embedSlideImages: true,
  enableLoginTools: false,
}
face.settings.sync()
if (activePresetId(settingsSlot.component({ t: (key) => key, settings: face.settings })) !== 'slides') {
  throw new Error('a hand-written slides config did not highlight the slides preset')
}
formState.value = { ...formState.value, slidesAsSource: false }
face.settings.sync()
if (activePresetId(settingsSlot.component({ t: (key) => key, settings: face.settings })) !== null) {
  throw new Error('a partial slides config must not highlight a preset')
}
formState.value = { ...formState.value, slidesAsSource: true }
face.settings.sync()
if (activePresetId(settingsSlot.component({ t: (key) => key, settings: face.settings })) !== 'slides') {
  throw new Error('restoring the slides switch did not restore the highlight')
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
  presets: initialPresetIds,
  activePreset: activePresetId(settingsSlot.component({ t: (key) => key, settings: face.settings })),
  calls: manualCalls,
  presetCalls,
  writable: initial.writable,
})}\n`)

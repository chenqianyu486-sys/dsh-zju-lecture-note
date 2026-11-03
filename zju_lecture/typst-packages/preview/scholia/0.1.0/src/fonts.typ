// Font roles as fallback lists: the "nice" face first, an embedded face last.
// Typst embeds Libertinus Serif, New Computer Modern (+ Math), DejaVu Sans Mono —
// so every list degrades to something that exists everywhere, zero install.
// (A Typst package cannot ship fonts; downstream users only have embedded +
//  their own system fonts. Missing first choices just warn and fall back.)
//
// 本项目补丁（由 tools/vendor_typst_packages.py 重放，见 VENDORED.md）：
// 上游把 Optima / Avenir Next / Menlo / Songti SC 放在首选位，它们都是商业
// 专有字体，命中后会被子集嵌进 PDF，产物就不适合再分发。这里统一换成
// 可再分发栈：STIX Two / Libertinus（Typst 内嵌）/ 随包 Notes Kai SC 与
// Notes Serif SC / Noto / Source Han（OFL）。

#let default-fonts = (
  body: ("STIX Two Text", "Libertinus Serif"),
  math: ("STIX Two Math", "New Computer Modern Math"),
  heading: (
    "STIX Two Text", "Libertinus Serif",
    "Notes Kai SC", "Notes Serif SC", "Noto Serif SC", "Source Han Serif SC",
  ),
  sans: (
    "STIX Two Text", "Libertinus Serif",
    "Notes Kai SC", "Notes Serif SC", "Noto Sans SC", "Source Han Sans SC",
  ),
  mono: ("DejaVu Sans Mono", "Notes Kai SC", "Notes Serif SC"),
  cjk: ("Notes Kai SC", "Notes Serif SC", "Noto Serif SC", "Source Han Serif SC"),
)

// shallow-merge user overrides over the defaults
#let resolve-fonts(overrides) = {
  let f = default-fonts
  if overrides != none {
    for (k, v) in overrides { f.insert(k, v) }
  }
  f
}

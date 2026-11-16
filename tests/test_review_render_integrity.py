"""Review regressions: preserve source meaning and publish current render artifacts."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from zju_lecture import handout, note_lint, study_notes


class TestMathAndReferenceIntegrity(unittest.TestCase):
    def test_blackboard_symbols_keep_their_letters(self):
        for expression, expected in (
            (r"\mathbb{E}[X]", "bb(E)[X]"),
            (r"\mathbb{P}(A)", "bb(P)(A)"),
            (r"\mathbb{H}", "bb(H)"),
            (r"\mathbb{R}", "RR"),
        ):
            with self.subTest(expression=expression):
                converted, warnings = study_notes.latex_to_typst(expression)
                self.assertEqual(converted, expected)
                self.assertEqual(warnings, [])
                self.assertEqual(study_notes.latex_to_typst(converted)[0], converted)

    def test_email_and_unknown_reference_keep_all_characters(self):
        result = study_notes.render_typst(
            "Contact someone@example.com today; @missing is text."
        )
        self.assertIn(r"someone\@example.com", result.typst)
        self.assertIn(r"\@missing is text.", result.typst)

    def test_known_reference_is_still_a_reference(self):
        result = study_notes.render_typst("[定义] Test —— Body <def:x>\n\n见 @def:x")
        self.assertIn("@def:x", result.typst)
        self.assertNotIn(r"\@def:x", result.typst)

    def test_unknown_reference_underscore_remains_literal(self):
        result = study_notes.render_typst("See @missing_label here.")
        self.assertIn(r"\@missing\_label", result.typst)


class TestCodePreservation(unittest.TestCase):
    def test_study_inline_code_is_not_math_or_an_html_comment(self):
        code = r"$\frac{1}{2}$ <!-- example -->"
        result = study_notes.render_typst("Use `" + code + "` literally.")
        self.assertIn(code, result.typst)
        self.assertEqual(result.warnings, [])

    def test_study_fenced_code_keeps_indentation_and_inner_markdown(self):
        code = '# Cover\n<!-- example -->\nif True:\n    print("$\\frac12$")'
        result = study_notes.render_typst("## Example\n\n```python\n" + code + "\n```")
        self.assertIn("#raw(" + json.dumps(code, ensure_ascii=False), result.typst)
        self.assertEqual(result.warnings, [])

    def test_handout_code_comments_and_nested_fences_are_literal(self):
        code = "# Cover\n```html\n<!-- example -->\n<p>x</p>\n```"
        result = handout.render_handout("# Test\n\n````markdown\n" + code + "\n````")
        self.assertIn("#raw(" + json.dumps(code, ensure_ascii=False), result.typst)
        self.assertEqual(result.title, "Test")
        self.assertEqual(result.warnings, [])

    def test_handout_inline_comment_example_is_not_removed(self):
        result = handout.render_handout("# Test\n\nUse `<!-- example -->` literally.")
        self.assertIn('#raw("<!-- example -->")', result.typst)

    def test_code_heading_does_not_become_a_fallback_cover(self):
        result = handout.render_handout("```python\n# important comment\nprint(1)\n```")
        self.assertEqual(result.title, "")
        self.assertIn('#raw("# important comment\\nprint(1)"', result.typst)

    def test_fixer_and_linter_respect_fence_length_and_character(self):
        for opening, inner, closing in (
            ("````markdown", "```latex", "````"),
            ("~~~markdown", "```latex", "~~~"),
        ):
            with self.subTest(opening=opening):
                code = opening + "\n" + inner + "\n$$\\frac12$$\n```\n" + closing + "\n"
                self.assertEqual(note_lint.fix_markdown(code), (code, []))
                self.assertEqual(note_lint.check_markdown(code), [])

    def test_fixing_resumes_after_the_actual_closing_fence(self):
        code = "````markdown\n```latex\n\\frac12\n```\n````\n"
        result, applied = note_lint.fix_markdown(code + "\n$\\frac12$\n")
        self.assertEqual(result, code + "\n$\\frac{1}{2}$\n")
        self.assertTrue(applied)

    def test_multibacktick_inline_code_is_not_linted(self):
        self.assertEqual(note_lint.check_markdown("Use ``a ` $\\frac12$`` literally."), [])


@unittest.skipUnless(study_notes.find_typst(), "Typst unavailable")
class TestPublishedPngSet(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="zju-render-integrity-")
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.project = self.root / "project"
        patcher = mock.patch.dict(os.environ, {"ZJU_TYPST_AUTO_INSTALL": "0"})
        patcher.start()
        self.addCleanup(patcher.stop)

    def compile(self, text, **kwargs):
        return study_notes.compile_project(str(self.project), text,
                                           workspace_root=str(self.root), **kwargs)

    def png_names(self):
        return sorted(path.name for path in self.project.glob("page-*.png"))

    def test_shorter_document_and_page_selection_replace_the_old_set(self):
        text = "One\n#pagebreak()\nTwo\n#pagebreak()\nThree"
        self.assertTrue(self.compile(text).ok)
        self.assertEqual(self.png_names(), ["page-1.png", "page-2.png", "page-3.png"])
        result = self.compile("New single page")
        self.assertTrue(result.ok, result.output)
        self.assertEqual(self.png_names(), ["page-1.png"])
        self.assertEqual([Path(p).name for p in result.png_paths], ["page-1.png"])
        result = self.compile(text, pages="2")
        self.assertTrue(result.ok, result.output)
        self.assertEqual(self.png_names(), ["page-2.png"])
        self.assertEqual([Path(p).name for p in result.png_paths], ["page-2.png"])

    def test_pdf_failure_preserves_the_previous_pdf_and_pngs(self):
        self.assertTrue(self.compile("Old page").ok)
        before = {name: (self.project / name).read_bytes()
                  for name in ("out.pdf", "page-1.png")}
        result = self.compile("#this_function_does_not_exist()")
        self.assertFalse(result.ok)
        self.assertEqual(result.png_paths, [])
        for name, data in before.items():
            self.assertEqual((self.project / name).read_bytes(), data)

    def test_png_failure_does_not_publish_partial_or_stale_images(self):
        self.assertTrue(self.compile("Old page").ok)
        custom = self.project / "page-diagram.png"
        custom.write_bytes(b"user image")
        run = study_notes._run_typst

        def fail_png(typst, args, cwd, timeout):
            if args[-1].endswith(".png"):
                (Path(cwd) / "page-1.png").write_bytes(b"partial PNG")
                return 1, "error: synthetic PNG export failure"
            return run(typst, args, cwd, timeout)

        with mock.patch.object(study_notes, "_run_typst", side_effect=fail_png):
            result = self.compile("New page")
        self.assertTrue(result.ok, result.output)
        self.assertTrue(result.warnings)
        self.assertEqual(result.png_paths, [])
        self.assertEqual(self.png_names(), ["page-diagram.png"])
        self.assertEqual(custom.read_bytes(), b"user image")

    def test_pdf_only_rebuild_removes_old_generated_pngs(self):
        self.assertTrue(self.compile("Old page").ok)
        result = self.compile("New page", make_png=False)
        self.assertTrue(result.ok, result.output)
        self.assertEqual(result.png_paths, [])
        self.assertEqual(self.png_names(), [])

    def test_blackboard_symbols_compile_in_both_renderers(self):
        markdown = r"The expectation is $\mathbb{E}[X]$ and the probability is $\mathbb{P}(A)$."
        for render in (study_notes.render_typst, handout.render_handout):
            with self.subTest(renderer=render.__name__):
                rendered = render(markdown)
                result = self.compile(rendered.typst, make_png=False)
                self.assertTrue(result.ok, result.output)
                self.assertIn("bb(E)", rendered.typst)
                self.assertIn("bb(P)", rendered.typst)


if __name__ == "__main__":
    unittest.main()

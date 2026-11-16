"""Derived study-note outputs must not follow workspace links (review 01)."""
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import mcp_server
from zju_lecture import study_notes


class TestStudyOutputBoundary(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="zju-output-review-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.ws = self.root / "workspace"
        self.outside = self.root / "outside"
        self.ws.mkdir()
        self.outside.mkdir()
        self.note = self.ws / "lecture.md"
        self.note.write_text("# Lecture\nSynthetic note.\n", encoding="utf-8")
        env = mock.patch.dict(os.environ, {
            "ZJU_WORKSPACE": str(self.ws), "PWD": str(self.ws),
            "ZJU_ENABLE_STUDY_NOTES": "1", "ZJU_TYPST_AUTO_INSTALL": "0",
        })
        env.start()
        self.addCleanup(env.stop)

    def link(self, target, link, directory=False):
        try:
            os.symlink(target, link, target_is_directory=directory)
        except OSError as exc:
            self.skipTest(str(exc))

    def compile(self):
        return mcp_server.handle_tool_call("zju_build_study_notes", {
            "mode": "compile", "draft_path": str(self.note), "make_png": False,
        })

    def test_project_directory_link_cannot_write_external_source(self):
        (self.outside / "main.typ").write_text("KEEP ME", encoding="utf-8")
        self.link(self.outside, self.ws / "lecture-typst", True)
        result = self.compile()
        self.assertIn("拒绝", result)
        self.assertEqual((self.outside / "main.typ").read_text(), "KEEP ME")
        self.assertFalse((self.outside / "out.pdf").exists())

    def test_derived_file_links_cannot_write_external_files(self):
        for index, name in enumerate(("main.typ", "prelude.typ", "out.pdf", "page-1.png")):
            with self.subTest(name=name):
                self.note = self.ws / ("case%d.md" % index)
                self.note.write_text("# Lecture\nSynthetic note.\n", encoding="utf-8")
                project = self.ws / ("case%d-typst" % index)
                project.mkdir()
                victim = self.outside / name
                victim.write_bytes(b"KEEP ME")
                self.link(victim, project / name)
                result = self.compile()
                self.assertIn("拒绝", result)
                self.assertEqual(victim.read_bytes(), b"KEEP ME")
                (project / name).unlink()

    def test_deliverable_pdf_link_cannot_overwrite_external_file(self):
        victim = self.outside / "victim.pdf"
        victim.write_bytes(b"KEEP ME")
        self.link(victim, self.ws / "lecture.pdf")
        result = self.compile()
        self.assertIn("拒绝", result)
        self.assertEqual(victim.read_bytes(), b"KEEP ME")

    @unittest.skipUnless(study_notes.find_typst(), "Typst unavailable")
    def test_regular_project_still_compiles(self):
        result = self.compile()
        self.assertIn("PDF:", result)
        self.assertTrue((self.ws / "lecture.pdf").read_bytes().startswith(b"%PDF-"))


if __name__ == "__main__":
    unittest.main()

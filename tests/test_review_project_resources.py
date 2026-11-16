"""The private compile stage retains safe project-relative resource access."""
import builtins
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from zju_lecture import study_notes


@unittest.skipUnless(study_notes.find_typst(), "Typst unavailable")
class TestProjectResourceSnapshot(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="zju-project-resources-")
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.workspace = self.root / "workspace"
        self.project = self.workspace / "project"
        self.project.mkdir(parents=True)
        self.outside = self.root / "outside"
        self.outside.mkdir()
        patcher = mock.patch.dict(os.environ, {"ZJU_TYPST_AUTO_INSTALL": "0"})
        patcher.start()
        self.addCleanup(patcher.stop)

    def write(self, name, text):
        path = self.project / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def compile(self, source, **kwargs):
        return study_notes.compile_project(str(self.project), source, make_png=False, **kwargs)

    def link(self, target, path, directory=False):
        try:
            os.symlink(target, path, target_is_directory=directory)
        except OSError as exc:
            self.skipTest(str(exc))

    def test_relative_read_nested_include_and_image_still_compile(self):
        fixture = self.write("fixture.txt", "Root resource")
        self.write("assets/text.txt", "Nested resource")
        self.write("parts/chapter.typ",
                   '#assert(read("../assets/text.txt") == "Nested resource")\n'
                   '#read("../assets/text.txt")\n#include "nested/leaf.typ"')
        self.write("parts/nested/leaf.typ", '#read("../../fixture.txt")')
        self.write("assets/picture.svg",
                   '<svg xmlns="http://www.w3.org/2000/svg" width="8" height="8">'
                   '<rect width="8" height="8" fill="blue"/></svg>')
        source = ('#assert(read("fixture.txt") == "Root resource")\n'
                  '#read("fixture.txt")\n#include "parts/chapter.typ"\n'
                  '#image("assets/picture.svg")')
        result = self.compile(source)
        self.assertTrue(result.ok, result.output)
        self.assertTrue(Path(result.pdf_path).read_bytes().startswith(b"%PDF-"))
        self.assertEqual(fixture.read_text(encoding="utf-8"), "Root resource")
        self.assertEqual(list(self.project.glob(".zju-build-*")), [])

    def test_file_resource_link_is_rejected_before_reading_external_data(self):
        secret = self.outside / "secret.txt"
        secret.write_text("EXTERNAL RESOURCE", encoding="utf-8")
        self.link(secret, self.project / "linked.txt")
        original_open = builtins.open

        def guarded_open(file, *args, **kwargs):
            if not isinstance(file, int) and os.path.realpath(file) == os.path.realpath(secret):
                raise AssertionError("external resource was opened")
            return original_open(file, *args, **kwargs)

        with mock.patch("builtins.open", side_effect=guarded_open):
            with self.assertRaises(study_notes.StudyNotesError):
                self.compile('#read("linked.txt")', workspace_root=str(self.workspace))
        self.assertFalse((self.project / "main.typ").exists())
        self.assertFalse((self.project / "out.pdf").exists())
        self.assertEqual(secret.read_text(encoding="utf-8"), "EXTERNAL RESOURCE")

    def test_directory_resource_link_is_rejected_without_traversal(self):
        (self.outside / "secret.typ").write_text("EXTERNAL RESOURCE", encoding="utf-8")
        self.link(self.outside, self.project / "linked", directory=True)
        original_scandir = os.scandir

        def guarded_scandir(path):
            if os.path.realpath(path) == os.path.realpath(self.outside):
                raise AssertionError("external resource directory was traversed")
            return original_scandir(path)

        with mock.patch.object(os, "scandir", side_effect=guarded_scandir):
            with self.assertRaises(study_notes.StudyNotesError):
                self.compile('#include "linked/secret.typ"', workspace_root=str(self.workspace))
        self.assertFalse((self.project / "out.pdf").exists())

    def test_old_staging_tree_and_generated_pages_are_not_resources(self):
        old_stage = self.project / ".zju-build-old"
        old_stage.mkdir()
        self.link(self.outside, old_stage / "external", directory=True)
        old_page = self.write("page-9.png", "old generated page")
        result = self.compile('#read("page-9.png")', workspace_root=str(self.workspace))
        self.assertFalse(result.ok, "a previous generated page must not be copied into the stage")
        self.assertEqual(old_page.read_text(encoding="utf-8"), "old generated page")
        self.assertEqual(sorted(p.name for p in self.project.glob(".zju-build-*")),
                         [".zju-build-old"])


if __name__ == "__main__":
    unittest.main()

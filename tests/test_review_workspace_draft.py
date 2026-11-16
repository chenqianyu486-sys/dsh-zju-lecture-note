"""Review 03/10: one authoritative workspace and non-destructive drafts."""
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import mcp_server
from zju_lecture.paths import is_inside_workspace


class TestWorkspaceDraft(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="zju-draft-review-")
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.ws, self.outside, self.backup = [self.root / name for name in ("ws", "outside", "backup")]
        for path in (self.ws, self.outside, self.backup):
            path.mkdir()
        self.note = self.ws / "lecture.md"
        self.note.write_text("# Lecture\nOriginal source.\n", encoding="utf-8")
        env = mock.patch.dict(os.environ, {
            "ZJU_WORKSPACE": str(self.ws), "PWD": str(self.outside),
            "ZJU_ENABLE_STUDY_NOTES": "1", "ZJU_BACKUP_DIR": str(self.backup),
            "ZJU_TYPST_AUTO_INSTALL": "0",
        })
        env.start()
        self.addCleanup(env.stop)

    def draft(self, **kwargs):
        return mcp_server.handle_tool_call("zju_build_study_notes", {
            "mode": "draft", "note_path": str(self.note), **kwargs,
        })

    def test_fallback_pwd_is_not_an_authorized_output_root(self):
        self.assertFalse(is_inside_workspace(str(self.outside / "note.md")))

    def test_draft_and_compile_refuse_external_source_without_writing(self):
        source = self.outside / "source.md"
        source.write_text("# External\nOUTSIDE_SENTINEL", encoding="utf-8")
        for mode, argument in (("draft", "note_path"), ("compile", "draft_path")):
            with self.subTest(mode=mode):
                result = mcp_server.handle_tool_call("zju_build_study_notes", {
                    "mode": mode, argument: str(source), "make_png": False,
                })
                self.assertIn("拒绝访问工作区之外", result)
                self.assertNotIn("OUTSIDE_SENTINEL", result)
                self.assertEqual([p.name for p in self.outside.iterdir()], ["source.md"])

    def test_draft_refuses_to_overwrite_curated_content(self):
        self.draft()
        draft = self.ws / "lecture-填空底稿.md"
        draft.write_text("CURATED_SENTINEL", encoding="utf-8")
        result = self.draft()
        self.assertIn("overwrite=true", result)
        self.assertEqual(draft.read_text(encoding="utf-8"), "CURATED_SENTINEL")

    def test_explicit_overwrite_preserves_a_backup(self):
        self.draft()
        draft = self.ws / "lecture-填空底稿.md"
        draft.write_text("CURATED_SENTINEL", encoding="utf-8")
        result = self.draft(overwrite=True)
        self.assertIn("已生成填空底稿", result)
        self.assertIn("Original source", draft.read_text(encoding="utf-8"))
        self.assertEqual([p.read_text(encoding="utf-8") for p in self.backup.glob("*.bak")], ["CURATED_SENTINEL"])

    def test_invalid_explicit_workspace_does_not_fall_back_to_pwd(self):
        with mock.patch.dict(os.environ, {"ZJU_WORKSPACE": str(self.root / "missing")}):
            result = self.draft()
            self.assertIn("错误", result)
            self.assertFalse((self.outside / "lecture-填空底稿.md").exists())


if __name__ == "__main__":
    unittest.main()

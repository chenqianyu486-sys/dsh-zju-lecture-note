"""Exercise shipped bytes, staged manifests, and an installed wheel offline."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools import build_plugin, build_skill_manifest


class TestSkillLineEndings(unittest.TestCase):
    def test_legacy_validator_accepts_crlf(self):
        with tempfile.TemporaryDirectory(prefix="zju-crlf-") as directory:
            skill = Path(directory, "sample", "SKILL.md")
            skill.parent.mkdir()
            skill.write_bytes(b"---\r\nname: sample\r\ndescription: Example\r\n---\r\nBody\r\n")
            self.assertEqual(build_plugin.validate_skill(str(skill)), [])

    def test_manifest_generation_canonicalizes_shipped_text_bytes(self):
        with tempfile.TemporaryDirectory(prefix="zju-manifest-") as directory:
            root = Path(directory)
            skill = root / "skills" / "sample" / "SKILL.md"
            skill.parent.mkdir(parents=True)
            canonical = b"---\nname: sample\ndescription: Example\n---\nBody\n"
            skill.write_bytes(canonical)
            with mock.patch.object(build_skill_manifest, "ROOT", str(root)):
                manifest_path, _count = build_skill_manifest.build("sample", "1.0.0")
                expected = Path(manifest_path).read_bytes()
                skill.write_bytes(canonical.replace(b"\n", b"\r\n"))
                build_skill_manifest.build("sample", "1.0.0")
            self.assertEqual(Path(manifest_path).read_bytes(), expected)
            self.assertEqual(skill.read_bytes(), canonical)
            manifest = json.loads(expected)
            self.assertEqual(manifest["contentHash"], "sha256:" + hashlib.sha256(skill.read_bytes()).hexdigest())

    def test_node_frontmatter_accepts_crlf(self):
        result = subprocess.run(
            ["node", "tests/skill_frontmatter_smoke.mjs"], cwd=ROOT,
            capture_output=True, text=True, encoding="utf-8", timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


class TestLegacyDistribution(unittest.TestCase):
    def test_staged_skills_include_every_scholia_reference(self):
        with tempfile.TemporaryDirectory(prefix="zju-stage-") as directory:
            build_plugin.stage_package(directory)
            manifest = json.loads(Path(directory, ".minimax-plugin", "plugin.json").read_text(encoding="utf-8"))
            for entry in manifest["skills"]:
                self.assertTrue(Path(directory, entry).is_file(), entry)
            for source in (ROOT / "skills" / "scholia-notes").rglob("*"):
                if source.is_file():
                    self.assertEqual(Path(directory, source.relative_to(ROOT)).read_bytes(), source.read_bytes())

    def test_staging_rejects_a_missing_declared_skill(self):
        files = build_plugin.collect_package_files()
        missing = "skills/zju-lecture-summarizer-login/SKILL.md"
        with tempfile.TemporaryDirectory(prefix="zju-stage-missing-") as directory:
            with mock.patch.object(build_plugin, "collect_package_files", return_value=[p for p in files if p != missing]):
                with self.assertRaisesRegex(build_plugin.ValidationError, "zju-lecture-summarizer-login"):
                    build_plugin.stage_package(directory)

    def test_zip_contains_all_manifest_skills_and_scholia_references(self):
        with tempfile.TemporaryDirectory(prefix="zju-zip-runtime-") as directory:
            source = Path(directory, "source")
            source.mkdir()
            build_plugin.stage_package(str(source))
            with mock.patch.object(build_plugin, "REPO_ROOT", str(source)):
                archive_path = build_plugin.make_zip(directory, "test")
            with zipfile.ZipFile(archive_path) as archive:
                manifest = json.loads(archive.read("zju-lecture/.minimax-plugin/plugin.json"))
                names = set(archive.namelist())
                for entry in manifest["skills"]:
                    self.assertIn("zju-lecture/" + entry, names)
                self.assertIn("zju-lecture/skills/scholia-notes/references/format-spec.md", names)
                self.assertIn("zju-lecture/skills/scholia-notes/LICENSE", names)


@unittest.skipUnless(importlib.util.find_spec("setuptools"), "wheel integration requires setuptools in the test interpreter")
class TestInstalledWheel(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix="zju-wheel-runtime-")
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.root = Path(cls.temporary.name)
        source = cls.root / "source"
        source.mkdir()
        for name in ("pyproject.toml", "mcp_server.py", "README.md", "LICENSE"):
            shutil.copy2(ROOT / name, source / name)
        shutil.copytree(ROOT / "zju_lecture", source / "zju_lecture", ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        wheels = cls.root / "wheels"
        wheels.mkdir()
        built = subprocess.run(
            [sys.executable, "-c", "import setuptools.build_meta as b,sys; b.build_wheel(sys.argv[1])", str(wheels)],
            cwd=source, capture_output=True, text=True, encoding="utf-8", timeout=120,
        )
        if built.returncode:
            raise AssertionError(built.stdout + built.stderr)
        cls.installed = cls.root / "installed"
        wheel = next(wheels.glob("*.whl"))
        installed = subprocess.run(
            [sys.executable, "-m", "pip", "--disable-pip-version-check", "install", "--no-index", "--no-deps", "--no-compile", "--target", str(cls.installed), str(wheel)],
            cwd=cls.root, capture_output=True, text=True, encoding="utf-8", timeout=120,
        )
        if installed.returncode:
            raise AssertionError(installed.stdout + installed.stderr)
        cls.env = {**os.environ, "PYTHONPATH": str(cls.installed), "PYTHONUTF8": "1", "PYTHONDONTWRITEBYTECODE": "1", "ZJU_TYPST_AUTO_INSTALL": "0"}

    def test_installed_cli_runs_mcp_without_source_checkout(self):
        request = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "zju_parse_url", "arguments": {"url": "https://classroom.zju.edu.cn/livingroom?sub_id=123456"}}}
        result = subprocess.run(
            [sys.executable, "-m", "zju_lecture.cli", "mcp"],
            cwd=self.root, env=self.env, input=json.dumps(request) + "\n",
            capture_output=True, text=True, encoding="utf-8", timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        response = json.loads(result.stdout.strip())
        self.assertFalse(response["result"]["isError"])
        self.assertEqual(json.loads(response["result"]["content"][0]["text"])["sub_id"], "123456")

    def assert_vendor_complete(self):
        for source in (ROOT / "zju_lecture" / "typst-packages").rglob("*"):
            if source.is_file():
                relative = source.relative_to(ROOT)
                self.assertTrue((self.installed / relative).is_file(), str(relative))

    def test_installed_vendor_tree_contains_deep_styles_and_licenses(self):
        self.assert_vendor_complete()

    def test_installed_vendor_tree_compiles_with_an_empty_cache(self):
        self.assert_vendor_complete()
        probe = subprocess.run(
            [sys.executable, "-c", "import json; from zju_lecture import deps; print(json.dumps({'typst':deps.find_typst(),'packages':deps.package_path(),'fonts':deps.font_path()}))"],
            cwd=self.root, env=self.env, capture_output=True, text=True, encoding="utf-8", timeout=30,
        )
        self.assertEqual(probe.returncode, 0, probe.stderr)
        paths = json.loads(probe.stdout)
        if not paths["typst"]:
            self.skipTest("Typst is unavailable; no download during packaging verification")
        workspace = self.root / "compile"
        workspace.mkdir()
        shutil.copy2(self.installed / "zju_lecture" / "prelude.typ", workspace / "prelude.typ")
        main = workspace / "main.typ"
        main.write_text('#import "prelude.typ": *\n#show: scholia.with(theme: "light", prose: "notes")\n#show: use-palette\n= 安装包验证\n中文与公式 $x^2 + y^2 = 1$。\n', encoding="utf-8")
        output = workspace / "out.pdf"
        cache = workspace / "empty-cache"
        cache.mkdir()
        result = subprocess.run(
            [paths["typst"], "compile", "--package-path", paths["packages"], "--package-cache-path", str(cache), "--font-path", paths["fonts"], str(main), str(output)],
            cwd=workspace, env={**self.env, "HTTP_PROXY": "http://127.0.0.1:1", "HTTPS_PROXY": "http://127.0.0.1:1"},
            capture_output=True, text=True, encoding="utf-8", timeout=120,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue(output.read_bytes().startswith(b"%PDF"))
        self.assertEqual(list(cache.iterdir()), [], "vendored compilation should not populate the download cache")

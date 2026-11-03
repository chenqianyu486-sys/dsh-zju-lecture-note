"""v2.1.0：Typst 依赖自举、随包字体与离线 Typst 包。

这组测试守住的都是「新机器装完插件就能出 PDF」这条线：
- 资产清单与校验和必须是钉死的；
- vendor 的包必须带许可文件（否则等于分发了 MIT 代码却不带许可）；
- 字体必须是改名后的子集（不能叫 Noto，也不能超过体积预算）；
- 找不到 Typst 时不能联网重试、不能把写讲义变成失败；
- 有 Typst 时，离线包 + 随包字体要真能编译出 PDF。
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from zju_lecture import deps  # noqa: E402

TYPST = deps.find_typst()


class TestAssetManifest(unittest.TestCase):
    def test_manifest_lists_every_supported_platform(self):
        manifest = deps.load_manifest()
        self.assertEqual(manifest["version"], "0.15.1")
        self.assertEqual(manifest["min_version"], "0.13.0")
        expected = {
            "win32-x86_64",
            "win32-arm64",
            "darwin-x86_64",
            "darwin-arm64",
            "linux-x86_64",
            "linux-arm64",
        }
        self.assertEqual(set(manifest["assets"]), expected)

    def test_every_checksum_is_sha256(self):
        for platform, entry in deps.load_manifest()["assets"].items():
            self.assertEqual(len(entry["sha256"]), 64, platform)
            self.assertGreater(entry["size"], 1_000_000, platform)
            self.assertIn(entry["kind"], ("zip", "tar.xz"), platform)

    def test_platform_key_maps_the_current_interpreter(self):
        key = deps.platform_key()
        if key:
            self.assertIn(key, deps.load_manifest()["assets"])


class TestFindTypst(unittest.TestCase):
    def test_env_override_wins(self):
        fake = os.path.join(tempfile.mkdtemp(), "typst")
        with open(fake, "w", encoding="utf-8") as handle:
            handle.write("")
        with mock.patch.dict(os.environ, {deps.TYPST_ENV: fake}):
            self.assertEqual(deps.find_typst(), fake)

    def test_missing_everywhere_returns_none(self):
        with mock.patch.dict(os.environ, {}, clear=True), mock.patch(
            "shutil.which", return_value=None
        ), mock.patch.object(deps, "_candidate_paths", return_value=[]):
            self.assertIsNone(deps.find_typst())

    def test_probe_without_auto_install_never_downloads(self):
        with mock.patch.object(deps, "find_typst", return_value=None), mock.patch.object(
            deps, "install"
        ) as install:
            info = deps.probe(auto_install=False)
        install.assert_not_called()
        self.assertFalse(info.ok)
        self.assertTrue(info.notes)

    def test_auto_install_flag_defaults_on_and_can_be_disabled(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertTrue(deps.auto_install_enabled())
        for value in ("0", "false", "off", "no"):
            with mock.patch.dict(os.environ, {deps.AUTO_INSTALL_ENV: value}):
                self.assertFalse(deps.auto_install_enabled(), value)


class TestCompileArgs(unittest.TestCase):
    def test_package_font_and_cache_paths_are_passed(self):
        workspace = tempfile.mkdtemp()
        args = deps.compile_args(workspace)
        self.assertIn("--package-path", args)
        self.assertIn("--font-path", args)
        self.assertIn("--package-cache-path", args)
        self.assertEqual(args[args.index("--package-path") + 1], deps.package_path())
        self.assertEqual(args[args.index("--font-path") + 1], deps.font_path())
        self.assertEqual(
            args[args.index("--package-cache-path") + 1],
            os.path.join(workspace, ".zju-lecture", "typst-cache"),
        )
        self.assertTrue(os.path.isdir(deps.package_path()))
        self.assertTrue(os.path.isdir(deps.font_path()))

    def test_hostile_archive_paths_are_refused(self):
        import io
        import zipfile

        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("../escape.txt", "x")
        path = os.path.join(tempfile.mkdtemp(), "evil.zip")
        with open(path, "wb") as handle:
            handle.write(buffer.getvalue())
        with self.assertRaises(ValueError):
            deps._extract(path, "zip", tempfile.mkdtemp())

    def test_checksum_mismatch_is_rejected(self):
        manifest = deps.load_manifest()
        key = deps.platform_key()
        if key is None:
            self.skipTest("当前平台不在清单里")
        entry = manifest["assets"][key]

        def fake_download(url, target, retries=3):
            with open(target, "wb") as handle:
                handle.write(b"not the real archive")

        # 用临时缓存目录：别在开发机上留下 6 小时的失败冷却标记。
        with mock.patch.dict(os.environ, {"ZJU_TYPST_CACHE": tempfile.mkdtemp()}), mock.patch.object(
            deps, "_download", side_effect=fake_download
        ):
            info = deps.install(force=True)
        self.assertFalse(info.ok)
        self.assertTrue(any("SHA256" in note for note in info.notes), info.notes)
        self.assertEqual(entry["sha256"], manifest["assets"][key]["sha256"])


class TestVendoredPackages(unittest.TestCase):
    def test_all_six_packages_are_present_with_licences(self):
        manifest = deps.load_manifest()
        self.assertTrue(os.path.isdir(deps.package_path()))
        packages = {
            "scholia": ("0.1.0", "LICENSE"),
            "frame-it": ("2.0.0", "LICENSE"),
            "marginalia": ("0.3.1", "UNLICENSE"),
            "theoretic": ("0.3.1", "UNLICENSE"),
            "showybox": ("2.0.4", "LICENSE"),
            "noteworthy": ("0.4.0", "LICENSE"),
        }
        for name, (version, licence) in packages.items():
            directory = os.path.join(deps.package_path(), "preview", name, version)
            self.assertTrue(os.path.isdir(directory), name)
            self.assertTrue(os.path.isfile(os.path.join(directory, licence)), name)
            self.assertTrue(
                os.path.isfile(os.path.join(directory, "typst.toml")),
                f"{name}: typst.toml 是包解析的依据，不能删",
            )
            # 大 README 与模板不随包分发：既减体积，也避免来源不明的示例图。
            self.assertFalse(os.path.isfile(os.path.join(directory, "README.md")), name)

    def test_vendored_index_exists_and_names_licences(self):
        index = os.path.join(deps.package_path(), "VENDORED.md")
        self.assertTrue(os.path.isfile(index))
        with open(index, encoding="utf-8") as handle:
            text = handle.read()
        for name in ("scholia", "frame-it", "marginalia", "theoretic", "showybox", "noteworthy"):
            self.assertIn(name, text)
        self.assertIn("MIT", text)

    def test_total_vendored_size_stays_small(self):
        total = 0
        for current, _dirs, names in os.walk(deps.package_path()):
            for name in names:
                total += os.path.getsize(os.path.join(current, name))
        self.assertLess(total, 1_000_000, f"vendor 目录 {total/1e6:.1f} MB 超出预算")


class TestBundledFont(unittest.TestCase):
    def setUp(self):
        try:
            import fontTools  # noqa: F401
        except ImportError:  # pragma: no cover - 只在开发机有 fontTools
            self.skipTest("没有 fontTools，跳过字体元数据检查")

    def test_font_exists_and_is_renamed(self):
        from fontTools.ttLib import TTFont

        path = os.path.join(deps.font_path(), "NotesSerifSC-Subset.ttf")
        self.assertTrue(os.path.isfile(path), path)
        self.assertLess(os.path.getsize(path), 8 * 1024 * 1024)
        font = TTFont(path)
        families = {
            record.toUnicode()
            for record in font["name"].names
            if record.nameID in (1, 16)
        }
        self.assertEqual(families, {"Notes Serif SC"})
        # 变量轴保留，标题才有真正的粗体面。
        self.assertIn("fvar", font)
        font.close()

    def test_licence_bundle_ships_with_the_font(self):
        directory = deps.font_path()
        with open(os.path.join(directory, "OFL.txt"), encoding="utf-8") as handle:
            self.assertIn("SIL OPEN FONT LICENSE", handle.read())
        with open(os.path.join(directory, "FONT-NOTICE.md"), encoding="utf-8") as handle:
            notice = handle.read()
        self.assertIn("子集", notice)
        self.assertIn("OFL", notice)


class TestDoctorTool(unittest.TestCase):
    def test_tool_is_registered_and_always_on(self):
        import mcp_server

        names = [tool["name"] for tool in mcp_server.available_tools()]
        self.assertIn("zju_doctor", names)
        with mock.patch.dict(
            os.environ,
            {"ZJU_ENABLE_SLIDES": "0", "ZJU_ENABLE_STUDY_NOTES": "0", "ZJU_ENABLE_LOGIN_TOOLS": "0"},
        ):
            names = [tool["name"] for tool in mcp_server.available_tools()]
        self.assertIn("zju_doctor", names)

    def test_report_names_the_three_dependencies(self):
        import mcp_server

        with mock.patch.object(
            deps,
            "describe",
            wraps=deps.describe,
        ):
            report = mcp_server._doctor_report(False)
        self.assertIn("Python", report)
        self.assertIn("Typst", report)
        self.assertIn("随包字体", report)
        self.assertIn("Typst 包", report)

    def test_missing_typst_still_writes_the_note(self):
        import mcp_server

        directory = tempfile.mkdtemp()
        env = {
            "ZJU_WORKSPACE": directory,
            "ZJU_ENABLE_SLIDES": "0",
            "ZJU_ENABLE_STUDY_NOTES": "0",
            "ZJU_ENABLE_LOGIN_TOOLS": "0",
            "ZJU_RENDER_PDF": "1",
            "ZJU_TYPST_AUTO_INSTALL": "0",
        }
        from zju_lecture.deps import TypstInfo

        with mock.patch.dict(os.environ, env, clear=False), mock.patch(
            "zju_lecture.deps.probe", return_value=TypstInfo(notes=["未找到 Typst"])
        ):
            output = mcp_server.handle_tool_call(
                "zju_write_note",
                {
                    "sub_id": "123456",
                    "name": "知识总结-2026-10-28-复变函数",
                    "content": "# 复变函数\n\n留数定理。\n",
                },
            )
        self.assertIn("PDF 跳过", output)
        self.assertIn("zju_doctor", output)
        self.assertTrue(
            os.path.isfile(os.path.join(directory, "知识总结-2026-10-28-复变函数.md"))
        )


@unittest.skipUnless(TYPST, "本机没有 Typst，跳过真实编译")
class TestOfflineCompile(unittest.TestCase):
    def test_vendored_packages_and_font_compile_without_network(self):
        workspace = tempfile.mkdtemp()
        cache = os.path.join(workspace, "empty-cache")
        os.makedirs(cache, exist_ok=True)
        main = os.path.join(workspace, "main.typ")
        with open(main, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(
                '#set text(font: ("Notes Serif SC", "SimSun"), lang: "zh", size: 11pt)\n'
                '= 保角映射\n'
                "解析函数与共形映射。\n"
            )
        output = os.path.join(workspace, "out.pdf")
        completed = subprocess.run(
            [
                TYPST,
                "compile",
                "--package-path",
                deps.package_path(),
                "--package-cache-path",
                cache,
                "--font-path",
                deps.font_path(),
                main,
                output,
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=120,
            cwd=workspace,
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.assertTrue(os.path.isfile(output))
        self.assertNotIn("unknown font family: notes serif sc", completed.stderr.lower())


class TestPackagingIncludesAssets(unittest.TestCase):
    def test_npm_files_cover_the_new_assets(self):
        with open(os.path.join(ROOT, "package.json"), encoding="utf-8") as handle:
            files = json.load(handle)["files"]
        for entry in ("zju_lecture/fonts", "zju_lecture/typst-packages", "zju_lecture/typst_assets.json"):
            self.assertIn(entry, files)

    def test_mcode_package_collects_the_new_assets(self):
        sys.path.insert(0, os.path.join(ROOT, "tools"))
        import build_plugin

        files = build_plugin.collect_package_files()
        joined = "\n".join(files)
        self.assertIn("zju_lecture/fonts/NotesSerifSC-Subset.ttf", joined)
        self.assertIn("zju_lecture/fonts/OFL.txt", joined)
        self.assertIn("zju_lecture/typst-packages/preview/scholia/0.1.0/LICENSE", joined)
        self.assertIn("zju_lecture/typst_assets.json", joined)


if __name__ == "__main__":
    unittest.main()

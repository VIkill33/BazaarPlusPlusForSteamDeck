import io
import os
import stat
import struct
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from backend.bpp import installer
from backend.bpp.models import Release


class UnusedReleaseSource:
    def latest(self):
        raise AssertionError("not used")

    def acquire_payload(self, release, working_dir, progress):
        raise AssertionError("not used")


class ArchiveSafetyTests(unittest.TestCase):
    def _archive(self, entries):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            for name, contents in entries:
                archive.writestr(name, contents)
        buffer.seek(0)
        return zipfile.ZipFile(buffer)

    def test_rejects_parent_absolute_and_symlink_entries(self):
        symlink = zipfile.ZipInfo("link")
        symlink.external_attr = (stat.S_IFLNK | 0o777) << 16
        for entry in ("../outside", "/absolute"):
            with self.subTest(entry=entry), self._archive([(entry, b"bad")]) as archive:
                with self.assertRaisesRegex(RuntimeError, "不安全路径"):
                    installer._safe_zip_members(archive)
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr(symlink, "target")
        buffer.seek(0)
        with zipfile.ZipFile(buffer) as archive, self.assertRaisesRegex(
            RuntimeError, "不安全路径"
        ):
            installer._safe_zip_members(archive)

    def test_rejects_extracted_size_over_limit(self):
        with self._archive([("large", b"12345")]) as archive, mock.patch.object(
            installer, "MAX_EXTRACTED_BYTES", 4
        ), self.assertRaisesRegex(RuntimeError, "安全大小限制"):
            installer._safe_zip_members(archive)


class PayloadVersionTests(unittest.TestCase):
    def _extract(self, payload_version, expected_version):
        entries = [
            ("winhttp.dll", b"dll"),
            ("doorstop_config.ini", b"config"),
            ("BepInEx/plugins/BazaarPlusPlus.dll", b"plugin"),
            ("BepInEx/plugins/BazaarPlusPlus.version", payload_version),
        ]
        with tempfile.TemporaryDirectory() as root_name:
            archive_path = Path(root_name) / "payload.zip"
            with zipfile.ZipFile(archive_path, "w") as archive:
                for name, contents in entries:
                    archive.writestr(name, contents)
            staging = Path(root_name) / "staging"
            staging.mkdir()
            installer._extract_payload(archive_path, staging, expected_version)

    def test_accepts_exact_and_prod_versions(self):
        for payload_version in (b"1.2.3", b"1.2.3.prod", b"1.2.3.PrOd"):
            with self.subTest(payload_version=payload_version):
                self._extract(payload_version, "1.2.3")

    def test_rejects_invalid_versions(self):
        for payload_version in (b"1.2.4", b"  \n", b"1.2.3\xff"):
            with self.subTest(payload_version=payload_version), self.assertRaises(
                RuntimeError
            ):
                self._extract(payload_version, "1.2.3")

    def test_rejects_payload_missing_required_file(self):
        with tempfile.TemporaryDirectory() as root_name:
            root = Path(root_name)
            payload = root / "payload.zip"
            with zipfile.ZipFile(payload, "w") as archive:
                archive.writestr("winhttp.dll", b"dll")
            staging = root / "staging"
            staging.mkdir()
            with self.assertRaisesRegex(RuntimeError, "缺少"):
                installer._extract_payload(payload, staging, "1.2.3")


class InstallTransactionTests(unittest.TestCase):
    def _trees(self, root: Path):
        game = root / "game"
        staging = root / "staging"
        (game / "BepInEx/config").mkdir(parents=True)
        (game / "BepInEx/plugins").mkdir(parents=True)
        (staging / "BepInEx/plugins").mkdir(parents=True)
        (game / installer.BPP_CONFIG).write_text("saved=true", "utf-8")
        (staging / "BepInEx/config").mkdir(parents=True)
        (staging / installer.BPP_CONFIG).write_text("default=false", "utf-8")
        (game / "BepInEx/plugins/OtherMod.dll").write_bytes(b"other")
        (game / "BepInEx/plugins/BazaarPlusPlus.dll").write_bytes(b"old")
        (game / "BepInEx/plugins/System.Memory.dll").write_bytes(b"stale")
        (staging / "BepInEx/plugins/BazaarPlusPlus.dll").write_bytes(b"new")
        (staging / "BepInEx/plugins/BazaarPlusPlus.version").write_text(
            "9.9.9", "utf-8"
        )
        (staging / "winhttp.dll").write_bytes(b"doorstop")
        (staging / "doorstop_config.ini").write_text("enabled=true", "utf-8")
        return game, staging

    def test_install_preserves_config_and_other_plugins_and_removes_stale(self):
        with tempfile.TemporaryDirectory() as root_name:
            game, staging = self._trees(Path(root_name))
            installer._apply_staged_payload(staging, game)
            self.assertEqual(
                (game / "BepInEx/plugins/BazaarPlusPlus.dll").read_bytes(), b"new"
            )
            self.assertEqual((game / installer.BPP_CONFIG).read_text(), "saved=true")
            self.assertTrue((game / "BepInEx/plugins/OtherMod.dll").is_file())
            self.assertFalse((game / "BepInEx/plugins/System.Memory.dll").exists())

    def test_write_failure_rolls_back_replaced_and_stale_files(self):
        with tempfile.TemporaryDirectory() as root_name:
            game, staging = self._trees(Path(root_name))
            real_replace = os.replace
            calls = 0

            def fail_second(source, destination):
                nonlocal calls
                calls += 1
                if calls == 2:
                    raise OSError("injected write failure")
                return real_replace(source, destination)

            with mock.patch.object(installer.os, "replace", side_effect=fail_second):
                with self.assertRaisesRegex(OSError, "injected write failure"):
                    installer._apply_staged_payload(staging, game)
            self.assertEqual(
                (game / "BepInEx/plugins/BazaarPlusPlus.dll").read_bytes(), b"old"
            )
            self.assertEqual(
                (game / "BepInEx/plugins/System.Memory.dll").read_bytes(), b"stale"
            )
            self.assertEqual(list(game.rglob("*.bpp-new")), [])

    def test_backup_failure_does_not_touch_game(self):
        with tempfile.TemporaryDirectory() as root_name:
            game, staging = self._trees(Path(root_name))
            with mock.patch.object(
                installer.shutil, "copy2", side_effect=OSError("backup failed")
            ), self.assertRaisesRegex(OSError, "backup failed"):
                installer._apply_staged_payload(staging, game)
            self.assertEqual(
                (game / "BepInEx/plugins/BazaarPlusPlus.dll").read_bytes(), b"old"
            )

    def test_rollback_failure_is_not_silently_swallowed(self):
        with tempfile.TemporaryDirectory() as root_name:
            game, staging = self._trees(Path(root_name))
            real_copy = installer.shutil.copy2
            copy_calls = 0

            def fail_write_and_rollback(source, destination, *args, **kwargs):
                nonlocal copy_calls
                copy_calls += 1
                if copy_calls == 6:
                    raise OSError("write failed")
                if copy_calls > 6:
                    raise OSError("rollback failed")
                return real_copy(source, destination, *args, **kwargs)

            with mock.patch.object(
                installer.shutil, "copy2", side_effect=fail_write_and_rollback
            ), self.assertRaises(OSError) as raised:
                installer._apply_staged_payload(staging, game)
            self.assertIn(str(raised.exception), {"write failed", "rollback failed"})


class SteamDeckPanelFontScaleTests(unittest.TestCase):
    def test_valid_metadata_does_not_use_legacy_method_numbers(self):
        # In 6.0 these old tokens identify unrelated methods, not UI helpers.
        with tempfile.TemporaryDirectory() as root_name:
            plugin = Path(root_name) / "plugin.dll"
            original = b"\x1f\x0c" + bytes.fromhex("28a40a0006")
            plugin.write_bytes(original)
            with mock.patch.object(installer, "_parse_dotnet_metadata", return_value=({}, {}, {}, {})):
                self.assertEqual(installer._scale_steam_deck_panel_font_sizes(plugin, "medium"), 0)
            self.assertEqual(plugin.read_bytes(), original)

    def test_scales_direct_and_helper_panel_font_sizes_to_medium(self):
        with tempfile.TemporaryDirectory() as root_name:
            plugin = Path(root_name) / "BazaarPlusPlus.dll"
            direct_offset = 2
            direct_tail = bytes.fromhex("285302000a6fbe03000a")
            history_create_label_call = bytes.fromhex("28a40a0006")
            history_style_code_cell_call = bytes.fromhex("28aa0a0006")
            plugin.write_bytes(
                b"AA"
                + b"\x22"
                + struct.pack("<f", 12.0)
                + direct_tail
                + b"BB"
                + b"\x1f\x0a\x17\x28\x15\x01\x00\x06"
                + history_create_label_call
                + b"CC"
                + b"\x1f\x10\x28\x15\x01\x00\x06"
                + history_style_code_cell_call
                + b"DD"
                + b"\x1f\x0c"
            )

            changes = installer._scale_steam_deck_panel_font_sizes(plugin, "medium")

            data = plugin.read_bytes()
            self.assertEqual(changes, 3)
            self.assertEqual(
                struct.unpack("<f", data[direct_offset + 1 : direct_offset + 5])[0],
                24.0,
            )
            self.assertIn(
                b"\x1f\x14\x17\x28\x15\x01\x00\x06" + history_create_label_call,
                data,
            )
            self.assertIn(
                b"\x1f\x20\x28\x15\x01\x00\x06" + history_style_code_cell_call,
                data,
            )
            self.assertTrue(data.endswith(b"\x1f\x0c"))

    def test_small_font_size_keeps_original_payload(self):
        with tempfile.TemporaryDirectory() as root_name:
            plugin = Path(root_name) / "BazaarPlusPlus.dll"
            original = (
                b"\x22"
                + struct.pack("<f", 12.0)
                + bytes.fromhex("285302000a6fbe03000a")
                + b"\x1f\x0a\x17\x28\x15\x01\x00\x06"
                + bytes.fromhex("28a40a0006")
            )
            plugin.write_bytes(original)

            self.assertEqual(
                installer._scale_steam_deck_panel_font_sizes(plugin, "small"), 0
            )
            self.assertEqual(plugin.read_bytes(), original)

    def test_large_font_size_uses_triple_scale(self):
        with tempfile.TemporaryDirectory() as root_name:
            plugin = Path(root_name) / "BazaarPlusPlus.dll"
            helper_call = bytes.fromhex("28a40a0006")
            plugin.write_bytes(b"\x1f\x0e\x17\x28\x15\x01\x00\x06" + helper_call)

            self.assertEqual(
                installer._scale_steam_deck_panel_font_sizes(plugin, "large"), 1
            )
            self.assertIn(
                b"\x1f\x2a\x17\x28\x15\x01\x00\x06" + helper_call,
                plugin.read_bytes(),
            )

    def test_large_direct_panel_font_size_is_capped_to_double_scale(self):
        with tempfile.TemporaryDirectory() as root_name:
            plugin = Path(root_name) / "BazaarPlusPlus.dll"
            direct_tail = bytes.fromhex("28b902000a6fe604000a")
            plugin.write_bytes(b"\x22" + struct.pack("<f", 14.0) + direct_tail)

            self.assertEqual(
                installer._scale_steam_deck_panel_font_sizes(plugin, "large"), 1
            )
            self.assertEqual(struct.unpack("<f", plugin.read_bytes()[1:5])[0], 28.0)

    def test_large_panel_font_size_also_scales_steam_deck_layout_heights(self):
        with tempfile.TemporaryDirectory() as root_name:
            plugin = Path(root_name) / "BazaarPlusPlus.dll"
            style_height_tail = bytes.fromhex("28b902000a6fbd02000a")
            fixed_item_height_call = bytes.fromhex("6f040b000a")
            plugin.write_bytes(
                b"AA"
                + b"\x22"
                + struct.pack("<f", 22.0)
                + style_height_tail
                + b"BB"
                + b"\x22"
                + struct.pack("<f", 98.0)
                + fixed_item_height_call
                + b"CC"
            )

            self.assertEqual(
                installer._scale_steam_deck_panel_font_sizes(plugin, "large"), 2
            )
            data = plugin.read_bytes()
            self.assertEqual(
                struct.unpack("<f", data[3:7])[0],
                44.0,
            )
            fixed_height_offset = data.find(fixed_item_height_call) - 4
            self.assertEqual(
                struct.unpack("<f", data[fixed_height_offset : fixed_height_offset + 4])[
                    0
                ],
                196.0,
            )

    def test_known_4_5_tokens_still_patch_when_metadata_is_unavailable(self):
        with tempfile.TemporaryDirectory() as root_name:
            plugin = Path(root_name) / "BazaarPlusPlus.dll"
            direct_tail = bytes.fromhex("28b902000a6fe604000a")
            history_create_label_call = bytes.fromhex("281d0e0006")
            collection_create_label_call = bytes.fromhex("287a160006")
            plugin.write_bytes(
                b"\x22"
                + struct.pack("<f", 14.0)
                + direct_tail
                + b"\x1f\x0c\x17\x28\x15\x01\x00\x06"
                + history_create_label_call
                + b"\x1f\x0b\x16\x28\x3c\x01\x00\x06"
                + collection_create_label_call
            )

            self.assertEqual(
                installer._scale_steam_deck_panel_font_sizes(plugin, "medium"), 3
            )
            data = plugin.read_bytes()
            self.assertEqual(struct.unpack("<f", data[1:5])[0], 28.0)
            self.assertIn(
                b"\x1f\x18\x17\x28\x15\x01\x00\x06" + history_create_label_call,
                data,
            )
            self.assertIn(
                b"\x1f\x16\x16\x28\x3c\x01\x00\x06" + collection_create_label_call,
                data,
            )


class SteamDeckUiConfigTests(unittest.TestCase):
    def test_updates_existing_panel_font_without_touching_other_settings(self):
        with tempfile.TemporaryDirectory() as root_name:
            game = Path(root_name)
            config = game / installer.BPP_CONFIG
            config.parent.mkdir(parents=True)
            config.write_text(
                "\n".join(
                    [
                        "[StreamerMode]",
                        "EnableNameOverride = true",
                        "",
                        "[Appearance]",
                        "## Existing BepInEx comment",
                        "UiFont = SansSerif",
                        "",
                        "[Hotkeys]",
                        "ToggleHistoryPanel = <Keyboard>/f8",
                        "",
                    ]
                ),
                "utf-8",
            )

            installer._apply_steam_deck_ui_defaults(game)

            self.assertEqual(
                config.read_text("utf-8"),
                "\n".join(
                    [
                        "[StreamerMode]",
                        "EnableNameOverride = true",
                        "",
                        "[Appearance]",
                        "## Existing BepInEx comment",
                        "UiFont = LxgwWenKai",
                        "",
                        "[Hotkeys]",
                        "ToggleHistoryPanel = <Keyboard>/f8",
                        "",
                    ]
                ),
            )

    def test_adds_panel_font_to_existing_appearance_section(self):
        with tempfile.TemporaryDirectory() as root_name:
            game = Path(root_name)
            config = game / installer.BPP_CONFIG
            config.parent.mkdir(parents=True)
            config.write_text("[Appearance]\nOtherSetting = true\n", "utf-8")

            installer._apply_steam_deck_ui_defaults(game)

            contents = config.read_text("utf-8")
            self.assertIn(
                "[Appearance]\nOtherSetting = true\n\n## BazaarPlusPlus", contents
            )
            self.assertIn("UiFont = LxgwWenKai\n", contents)

    def test_creates_config_when_missing(self):
        with tempfile.TemporaryDirectory() as root_name:
            game = Path(root_name)

            installer._apply_steam_deck_ui_defaults(game)

            self.assertEqual(
                (game / installer.BPP_CONFIG).read_text("utf-8"),
                "\n".join(
                    [
                        "[Appearance]",
                        "",
                        "## BazaarPlusPlus in-game panel font family.",
                        "# Setting type: BppUiFontKind",
                        "# Default value: LxgwWenKai",
                        "# Acceptable values: LxgwWenKai, SansSerif",
                        "UiFont = LxgwWenKai",
                        "",
                    ]
                ),
            )

    def test_refuses_symlink_config_file(self):
        with tempfile.TemporaryDirectory() as root_name:
            root = Path(root_name)
            game = root / "game"
            outside = root / "outside.cfg"
            (game / "BepInEx/config").mkdir(parents=True)
            outside.write_text("[Appearance]\nUiFont = LxgwWenKai\n", "utf-8")
            (game / installer.BPP_CONFIG).symlink_to(outside)

            with self.assertRaisesRegex(RuntimeError, "符号链接"):
                installer._apply_steam_deck_ui_defaults(game)


class InstallerOrchestrationTests(unittest.TestCase):
    def test_reset_removes_current_and_legacy_data_without_touching_game(self):
        with tempfile.TemporaryDirectory() as root_name:
            game = Path(root_name)
            for name in ("BazaarPlusPlusV6", "BazaarPlusPlusV4"):
                (game / name).mkdir()
                (game / name / "data.json").write_text("saved")
            (game / "TheBazaar.exe").write_bytes(b"game")
            installer.Installer(UnusedReleaseSource()).reset_data(game)
            self.assertFalse((game / "BazaarPlusPlusV6").exists())
            self.assertFalse((game / "BazaarPlusPlusV4").exists())
            self.assertEqual((game / "TheBazaar.exe").read_bytes(), b"game")

    def test_reset_checks_all_data_paths_before_removing_any(self):
        with tempfile.TemporaryDirectory() as root_name:
            game = Path(root_name)
            (game / "BazaarPlusPlusV6").mkdir()
            (game / "outside").mkdir()
            (game / "BazaarPlusPlusV4").symlink_to(game / "outside", target_is_directory=True)
            with self.assertRaisesRegex(RuntimeError, "符号链接"):
                installer.Installer(UnusedReleaseSource()).reset_data(game)
            self.assertTrue((game / "BazaarPlusPlusV6").exists())

    def test_uninstall_removes_6_components_and_preserves_other_mods(self):
        private = (
            "BepInEx/plugins/BazaarPlusPlus.Core.dll",
            "BepInEx/plugins/BazaarPlusPlus.history-database.json",
            "BepInEx/plugins/BazaarPlusPlus.managed-manifest.txt",
            "BepInEx/patchers/BazaarPlusPlus.Updater.dll",
            "TheBazaar_Data/Plugins/x86_64/GfxPluginBppReplayMediaFoundation.dll",
        )
        for other_mod in (False, True):
            with self.subTest(other_mod=other_mod), tempfile.TemporaryDirectory() as root_name:
                game = Path(root_name)
                for name in (*private, "BepInEx/plugins/Microsoft.Data.Sqlite.dll"):
                    path = game / name
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(b"component")
                if other_mod:
                    (game / "BepInEx/plugins/OtherMod.dll").write_bytes(b"other")
                installer.Installer(UnusedReleaseSource()).uninstall(game)
                for name in private:
                    self.assertFalse((game / name).exists(), name)
                self.assertEqual((game / "BepInEx/plugins/Microsoft.Data.Sqlite.dll").exists(), other_mod)
                if other_mod:
                    self.assertEqual((game / "BepInEx/plugins/OtherMod.dll").read_bytes(), b"other")

    def test_install_acquires_validates_applies_and_reports_progress(self):
        class PayloadReleaseSource:
            def latest(self):
                raise AssertionError("not used")

            def acquire_payload(self, release, working_dir, progress):
                progress("准备安全解包工具", 12)
                progress("下载官方安装包", 15)
                progress("提取 BepInEx payload", 74)
                payload = working_dir / "payload.zip"
                with zipfile.ZipFile(payload, "w") as archive:
                    archive.writestr("winhttp.dll", b"dll")
                    archive.writestr("doorstop_config.ini", b"config")
                    archive.writestr(
                        "BepInEx/plugins/BazaarPlusPlus.dll", b"plugin"
                    )
                    archive.writestr(
                        "BepInEx/plugins/BazaarPlusPlus.version", release.version
                    )
                return payload

        with tempfile.TemporaryDirectory() as root_name:
            root = Path(root_name)
            game = root / "game"
            game.mkdir()
            progress = []
            target = installer.Installer(PayloadReleaseSource())
            target.install(
                Release("4.4.3", "https://example.invalid/installer.exe"),
                game,
                root / "runtime",
                lambda message, percent: progress.append((message, percent)),
            )
            self.assertEqual(target.installed_version(game), "4.4.3")
            self.assertEqual(
                progress,
                [
                    ("准备安全解包工具", 12),
                    ("下载官方安装包", 15),
                    ("提取 BepInEx payload", 74),
                    ("校验安装内容", 82),
                    ("应用 Steam Deck 面板字号设置", 86),
                    ("写入游戏目录", 90),
                    ("应用 Steam Deck UI 适配", 96),
                    ("安装完成", 100),
                ],
            )

    def test_rejects_symlink_destination_directory(self):
        with tempfile.TemporaryDirectory() as root_name:
            root = Path(root_name)
            game = root / "game"
            staging = root / "staging"
            outside = root / "outside"
            game.mkdir()
            staging.mkdir()
            outside.mkdir()
            (game / "BepInEx").symlink_to(outside, target_is_directory=True)
            (staging / "BepInEx/plugins").mkdir(parents=True)
            (staging / "BepInEx/plugins/file.dll").write_bytes(b"data")
            with self.assertRaisesRegex(RuntimeError, "符号链接目录"):
                installer._apply_staged_payload(staging, game)

    def test_rejects_absolute_and_parent_destinations(self):
        with self.assertRaisesRegex(RuntimeError, "不安全路径"):
            installer._assert_safe_destination(Path("/game"), Path("/outside"))
        with self.assertRaisesRegex(RuntimeError, "不安全路径"):
            installer._assert_safe_destination(Path("/game"), Path("../outside"))

    def test_plugin_directory_counts_as_third_party(self):
        with tempfile.TemporaryDirectory() as root_name:
            game = Path(root_name)
            (game / "BepInEx/plugins/SomeOtherMod").mkdir(parents=True)
            self.assertTrue(installer._third_party_plugins(game))

    def test_reset_refuses_symlink_data_directory(self):
        with tempfile.TemporaryDirectory() as root_name:
            root = Path(root_name)
            game = root / "game"
            outside = root / "outside"
            game.mkdir()
            outside.mkdir()
            (game / installer.DATA_DIRECTORY).symlink_to(
                outside, target_is_directory=True
            )
            with self.assertRaisesRegex(RuntimeError, "符号链接"):
                installer.Installer(UnusedReleaseSource()).reset_data(game)

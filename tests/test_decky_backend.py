import importlib.util
import io
import sys
import tempfile
import types
import unittest
import zipfile
from pathlib import Path
from unittest import mock


decky_stub = types.ModuleType("decky")
decky_stub.DECKY_USER_HOME = "/home/deck"
decky_stub.DECKY_PLUGIN_RUNTIME_DIR = "/tmp/bpp-runtime"
decky_stub.DECKY_PLUGIN_SETTINGS_DIR = "/tmp/bpp-settings"
decky_stub.logger = types.SimpleNamespace(info=lambda *args, **kwargs: None)


async def emit(*args):
    return None


decky_stub.emit = emit
sys.modules.setdefault("decky", decky_stub)

spec = importlib.util.spec_from_file_location(
    "bpp_decky_backend", Path(__file__).parents[1] / "main.py"
)
backend = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(backend)


class SteamDiscoveryTests(unittest.TestCase):
    def test_parse_vdf_paths_supports_escaped_backslashes(self):
        contents = r'''
        "libraryfolders"
        {
          "0" { "path" "/home/deck/.local/share/Steam" }
          "1" { "path" "D:\\SteamLibrary" }
        }
        '''
        self.assertEqual(
            backend._parse_vdf_paths(contents),
            [Path("/home/deck/.local/share/Steam"), Path(r"D:\SteamLibrary")],
        )

    def test_finds_game_from_library_manifest(self):
        with tempfile.TemporaryDirectory() as root_name:
            root = Path(root_name)
            home = root / "home/deck"
            steam = home / ".local/share/Steam"
            library = root / "sdcard"
            (steam / "steamapps").mkdir(parents=True)
            (steam / "steamapps/libraryfolders.vdf").write_text(
                f'"libraryfolders" {{ "1" {{ "path" "{library}" }} }}',
                "utf-8",
            )
            (library / "steamapps").mkdir(parents=True)
            (
                library / f"steamapps/appmanifest_{backend.APP_ID}.acf"
            ).write_text('"AppState" { "installdir" "Custom Bazaar" }', "utf-8")
            game = library / "steamapps/common/Custom Bazaar"
            game.mkdir(parents=True)
            (game / backend.GAME_EXECUTABLE).write_bytes(b"MZ")

            self.assertEqual(backend.find_game_path(home), game.resolve())


class ArchiveSafetyTests(unittest.TestCase):
    def _archive(self, entries):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            for name, contents in entries:
                archive.writestr(name, contents)
        buffer.seek(0)
        return zipfile.ZipFile(buffer)

    def test_rejects_parent_traversal(self):
        with self._archive([("../outside", b"bad")]) as archive:
            with self.assertRaisesRegex(RuntimeError, "不安全路径"):
                backend._safe_zip_members(archive)

    def test_accepts_expected_payload_paths(self):
        entries = [
            ("winhttp.dll", b"dll"),
            ("doorstop_config.ini", b"config"),
            ("BepInEx/plugins/BazaarPlusPlus.dll", b"plugin"),
            ("BepInEx/plugins/BazaarPlusPlus.version", b"1.2.3"),
        ]
        with tempfile.TemporaryDirectory() as root_name:
            archive_path = Path(root_name) / "payload.zip"
            with zipfile.ZipFile(archive_path, "w") as archive:
                for name, contents in entries:
                    archive.writestr(name, contents)
            staging = Path(root_name) / "staging"
            staging.mkdir()

            backend._extract_payload(archive_path, staging)

            self.assertEqual(
                (staging / "BepInEx/plugins/BazaarPlusPlus.version").read_text(),
                "1.2.3",
            )


class ReleaseMetadataTests(unittest.TestCase):
    def test_selects_verified_windows_asset(self):
        digest = "a" * 64
        fixture = {
            "tag_name": "v4.4.1",
            "body": "notes",
            "assets": [
                {
                    "name": "4.4.1_windows-x86_64_installer_BazaarPlusPlus.exe",
                    "browser_download_url": (
                        "https://github.com/cauyxy/BazaarPlusPlus/releases/"
                        "download/4.4.1/BazaarPlusPlus.exe"
                    ),
                    "digest": f"sha256:{digest}",
                    "size": 1234,
                }
            ],
        }
        with mock.patch.object(backend, "_request_json", return_value=fixture):
            release = backend._latest_release()

        self.assertEqual(release["version"], "4.4.1")
        self.assertEqual(release["sha256"], digest)

    def test_rejects_unverified_asset(self):
        fixture = {
            "tag_name": "4.4.1",
            "assets": [
                {
                    "name": "4.4.1_windows-x86_64_installer_BazaarPlusPlus.exe",
                    "browser_download_url": "https://github.com/example/file.exe",
                    "digest": None,
                    "size": 1234,
                }
            ],
        }
        with mock.patch.object(backend, "_request_json", return_value=fixture):
            with self.assertRaisesRegex(RuntimeError, "SHA-256"):
                backend._latest_release()


class InstallTransactionTests(unittest.TestCase):
    def test_install_preserves_config_and_other_plugins(self):
        with tempfile.TemporaryDirectory() as root_name:
            root = Path(root_name)
            game = root / "game"
            staging = root / "staging"
            (game / "BepInEx/config").mkdir(parents=True)
            (game / "BepInEx/plugins").mkdir(parents=True)
            (staging / "BepInEx/plugins").mkdir(parents=True)
            (game / backend.GAME_EXECUTABLE).write_bytes(b"MZ")
            (game / backend.BPP_CONFIG).write_text("saved=true", "utf-8")
            (game / "BepInEx/plugins/OtherMod.dll").write_bytes(b"other")
            (game / "BepInEx/plugins/BazaarPlusPlus.dll").write_bytes(b"old")
            (staging / "BepInEx/plugins/BazaarPlusPlus.dll").write_bytes(b"new")
            (staging / "BepInEx/plugins/BazaarPlusPlus.version").write_text(
                "9.9.9", "utf-8"
            )
            (staging / "winhttp.dll").write_bytes(b"doorstop")
            (staging / "doorstop_config.ini").write_text("enabled=true", "utf-8")

            backend._apply_staged_payload(staging, game)

            self.assertEqual(
                (game / "BepInEx/plugins/BazaarPlusPlus.dll").read_bytes(), b"new"
            )
            self.assertEqual((game / backend.BPP_CONFIG).read_text(), "saved=true")
            self.assertTrue((game / "BepInEx/plugins/OtherMod.dll").is_file())

    def test_plugin_directory_counts_as_third_party(self):
        with tempfile.TemporaryDirectory() as root_name:
            game = Path(root_name)
            (game / "BepInEx/plugins/SomeOtherMod").mkdir(parents=True)

            self.assertTrue(backend._third_party_plugins(game))


if __name__ == "__main__":
    unittest.main()

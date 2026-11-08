"""Offline integration check: python3 -m tests.compatibility.verify_payload PAYLOAD VERSION."""
import json
import sys
import tempfile
from pathlib import Path

from backend.bpp import installer
from backend.bpp.models import Release


def verify(payload: Path, version: str) -> dict:
    class LocalReleaseSource:
        def acquire_payload(self, release, working_dir, progress):
            return payload

    with tempfile.TemporaryDirectory(prefix="bpp-compat-") as directory:
        root = Path(directory)
        staging = root / "original"
        staging.mkdir()
        installer._extract_payload(payload, staging, version)
        art_compatibility = installer._bypass_legacy_collection_art_cache(staging / installer.BPP_PLUGIN, version)
        if version == "6.0.0":
            assert art_compatibility, "6.0.0 native card-art compatibility did not apply"
        original = (staging / installer.BPP_PLUGIN).read_bytes()
        counts = {}
        for preset in ("small", "medium", "large"):
            plugin = root / (preset + ".dll")
            plugin.write_bytes(original)
            counts[preset] = installer._scale_steam_deck_panel_font_sizes(plugin, preset)
            if preset == "small":
                assert plugin.read_bytes() == original
            else:
                assert counts[preset] > 0, "No supported font/layout sites found"
                assert len(plugin.read_bytes()) == len(original)
                installer._parse_dotnet_metadata(plugin.read_bytes())
        assert (root / "medium.dll").read_bytes() != (root / "large.dll").read_bytes()

        target = installer.Installer(LocalReleaseSource())
        release = Release(version, "https://example.invalid/unused.exe")
        for preset in counts:
            game = root / preset
            game.mkdir()
            target.install(release, game, root / "runtime", lambda *_: None, preset)
            assert target.installed_version(game) == version + ".prod"
            assert (game / installer.BPP_PLUGIN).read_bytes() == (root / (preset + ".dll")).read_bytes()
            config = game / installer.BPP_CONFIG
            config.write_text(config.read_text() + "\n[Custom]\nSaved = true\n")
            other = game / "BepInEx/plugins/OtherMod.dll"
            other.write_bytes(b"other")
            data = game / "BazaarPlusPlusV6"
            data.mkdir()
            (data / "saved.json").write_text("saved")
            target.install(release, game, root / "runtime", lambda *_: None, preset)
            assert "Saved = true" in config.read_text()
            assert (data / "saved.json").read_text() == "saved"
            assert other.read_bytes() == b"other"
            target.uninstall(game)
            for private in installer.BPP_PRIVATE_PATHS:
                assert not (game / private).exists(), private
            assert other.read_bytes() == b"other"
            assert (game / "BepInEx/plugins/Microsoft.Data.Sqlite.dll").is_file()
            target.reset_data(game)
            assert not data.exists()
        return {"version": version, "font_layout_changes": counts, "native_card_art_compatibility": art_compatibility,
                "fresh_install_upgrade_uninstall_reset": "passed for all presets",
                "configuration_data_other_mods_preserved": True}


if __name__ == "__main__":
    print(json.dumps(verify(Path(sys.argv[1]).resolve(), sys.argv[2]), indent=2))

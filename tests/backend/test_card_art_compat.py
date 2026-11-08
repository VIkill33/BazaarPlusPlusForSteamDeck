import struct
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from backend.bpp import installer


class CollectionArtCompatibilityTests(unittest.TestCase):
    def _metadata(self, *, namespace="BazaarPlusPlus.Patches.CollectionPanel", field="cardMaterial"):
        return (
            {1: installer._TypeDefInfo(namespace, "CollectionItemLoadArtPatch", 1, 2)},
            {1: installer._MethodDefInfo("Prefix", 123)},
            {1: installer._TypeRefInfo("TheBazaar.Assets.Scripts.ScriptableObjectsScripts", "CardAssetDataSO")},
            {1: installer._MemberRefInfo(field, 1, 1)},
        )

    def _patch(self, body, *, version="6.0.0", metadata=None):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        plugin = Path(temporary.name) / "BazaarPlusPlus.dll"
        plugin.write_bytes(b"BEFORE!!" + body + b"AFTER")
        original = plugin.read_bytes()
        with mock.patch.object(installer, "_parse_dotnet_metadata", return_value=metadata or self._metadata()), mock.patch.object(
            installer, "_rva_to_offset", return_value=8
        ):
            changed = installer._bypass_legacy_collection_art_cache(plugin, version)
        return changed, plugin, original

    def test_tiny_prefix_returns_true_and_preserves_surrounding_bytes(self):
        changed, plugin, original = self._patch(bytes([(4 << 2) | 2]) + b"\x16\x00\x00\x2a")
        self.assertTrue(changed)
        self.assertEqual(plugin.read_bytes(), original[:9] + b"\x17\x00\x00\x2a" + original[13:])

    def test_fat_prefix_returns_true_preserving_header_size_and_local_signature(self):
        header = struct.pack("<HHII", 0x3013, 8, 5, 0x11000001)
        changed, plugin, original = self._patch(header + b"\x16\x00\x00\x00\x2a")
        self.assertTrue(changed)
        self.assertEqual(plugin.read_bytes(), original[:20] + b"\x17\x00\x00\x00\x2a" + original[25:])

    def test_other_versions_are_unchanged(self):
        for version in ("4.5.0", "6.0.1", "7.0.0"):
            with self.subTest(version=version):
                changed, plugin, original = self._patch(b"ignored", version=version)
                self.assertFalse(changed)
                self.assertEqual(plugin.read_bytes(), original)

    def test_other_classes_and_updated_cache_are_unchanged(self):
        for metadata in (self._metadata(namespace="OtherMod"), self._metadata(field="newMaterial")):
            changed, plugin, original = self._patch(b"ignored", metadata=metadata)
            self.assertFalse(changed)
            self.assertEqual(plugin.read_bytes(), original)

    def test_unsupported_and_truncated_bodies_fail_without_writing(self):
        for body in (b"\x00", b"\x06\x2a", b"\xfe", struct.pack("<HHII", 0x300b, 8, 2, 0) + b"\x16\x2a"):
            with self.subTest(body=body), self.assertRaises(RuntimeError):
                self._patch(body)

    def test_reapplying_is_a_noop(self):
        body = bytes([(4 << 2) | 2]) + b"\x17\x00\x00\x2a"
        changed, plugin, original = self._patch(body)
        self.assertFalse(changed)
        self.assertEqual(plugin.read_bytes(), original)

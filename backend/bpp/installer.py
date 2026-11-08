import os
import shutil
import stat
import struct
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Iterable, Optional

from .models import Release, normalize_version
from .release import ProgressReporter, ReleaseSource


DATA_DIRECTORY = "BazaarPlusPlusV6"
LEGACY_DATA_DIRECTORY = "BazaarPlusPlusV4"
MAX_EXTRACTED_BYTES = 400 * 1024 * 1024
BPP_CONFIG = "BepInEx/config/BazaarPlusPlus.cfg"
BPP_PLUGIN = "BepInEx/plugins/BazaarPlusPlus.dll"
BPP_PRIVATE_PATHS = (
    BPP_CONFIG,
    BPP_PLUGIN,
    "BepInEx/plugins/BazaarPlusPlus.version",
    "BepInEx/plugins/BazaarPlusPlus.ModApi.dll",
    "BepInEx/plugins/BazaarPlusPlus.Storage.dll",
    "BepInEx/plugins/BazaarPlusPlus.Localization.dll",
    "BepInEx/plugins/BazaarPlusPlus.Core.dll",
    "BepInEx/plugins/BazaarPlusPlus.history-database.json",
    "BepInEx/plugins/BazaarPlusPlus.managed-manifest.txt",
    "BepInEx/patchers/BazaarPlusPlus.Updater.dll",
    "TheBazaar_Data/Plugins/x86_64/GfxPluginBppReplayMediaFoundation.dll",
)
BPP_DEPENDENCY_PATHS = (
    "BepInEx/plugins/Microsoft.Data.Sqlite.dll",
    "BepInEx/plugins/SQLitePCLRaw.batteries_v2.dll",
    "BepInEx/plugins/SQLitePCLRaw.core.dll",
    "BepInEx/plugins/SQLitePCLRaw.provider.e_sqlite3.dll",
    "BepInEx/plugins/SixLabors.ImageSharp.dll",
    "BepInEx/plugins/System.Buffers.dll",
    "BepInEx/plugins/System.Memory.dll",
    "BepInEx/plugins/System.Numerics.Vectors.dll",
    "BepInEx/plugins/System.Text.Encoding.CodePages.dll",
    "BepInEx/plugins/e_sqlite3.dll",
    "BepInEx/plugins/ffmpeg.exe",
    "BepInEx/plugins/ffmpeg-LICENSE.txt",
)
STEAM_DECK_UI_SECTION = "Appearance"
STEAM_DECK_UI_FONT_KEY = "UiFont"
STEAM_DECK_UI_FONT_VALUE = "LxgwWenKai"
STEAM_DECK_UI_FONT_BLOCK = (
    "## BazaarPlusPlus in-game panel font family.",
    "# Setting type: BppUiFontKind",
    "# Default value: LxgwWenKai",
    "# Acceptable values: LxgwWenKai, SansSerif",
    f"{STEAM_DECK_UI_FONT_KEY} = {STEAM_DECK_UI_FONT_VALUE}",
)
STEAM_DECK_FONT_BASE_SIZES = (10, 11, 12, 13, 14, 15, 16, 20, 28)
STEAM_DECK_FONT_SIZE_PRESETS = {
    "small": 1.0,
    "medium": 2.0,
    "large": 3.0,
}
STEAM_DECK_DIRECT_FONT_SIZE_PRESETS = {
    "small": 1.0,
    "medium": 2.0,
    "large": 2.0,
}
STEAM_DECK_LAYOUT_SIZE_PRESETS = {
    "small": 1.0,
    "medium": 1.5,
    "large": 2.0,
}
STEAM_DECK_LAYOUT_BASE_SIZES = (
    18,
    20,
    22,
    24,
    26,
    32,
    34,
    36,
    40,
    42,
    44,
    48,
    54,
    56,
    58,
    60,
    64,
    80,
    90,
    96,
    98,
    112,
    132,
)
KNOWN_UI_TOOLKIT_FONT_SIZE_TAILS = (
    bytes.fromhex("285302000a6fbe03000a"),  # 4.4.x
    bytes.fromhex("28b902000a6fe604000a"),  # 4.5.0
)
KNOWN_PANEL_FONT_HELPER_CALLS = (
    bytes.fromhex("28a40a0006"),  # HistoryPanelUiToolkitView.CreateLabel
    bytes.fromhex("28aa0a0006"),  # HistoryPanelUiToolkitView.StyleCodeCell
    bytes.fromhex("280f100006"),  # CollectionPanelView.CreateLabel
    bytes.fromhex("281d0e0006"),  # 4.5.0 HistoryPanelUiToolkitView.CreateLabel
    bytes.fromhex("28230e0006"),  # 4.5.0 HistoryPanelUiToolkitView.StyleCodeCell
    bytes.fromhex("287a160006"),  # 4.5.0 CollectionPanelView.CreateLabel
)
KNOWN_UI_TOOLKIT_LAYOUT_SIZE_TAILS = (
    bytes.fromhex("28b902000a6fbd02000a"),  # 4.5.0 IStyle.height
    bytes.fromhex("28b902000a6fbe02000a"),  # 4.5.0 IStyle.minHeight
    bytes.fromhex("28b902000a6fbf02000a"),  # 4.5.0 IStyle.maxHeight
)
KNOWN_FIXED_ITEM_HEIGHT_CALLS = (
    bytes.fromhex("6f040b000a"),  # 4.5.0 BaseVerticalCollectionView.fixedItemHeight
)


@dataclass(frozen=True)
class _MetadataToken:
    table: int
    row: int

    @property
    def value(self) -> int:
        return (self.table << 24) | self.row

    def call(self) -> bytes:
        return b"\x28" + struct.pack("<I", self.value)


@dataclass(frozen=True)
class _TypeDefInfo:
    namespace: str
    name: str
    method_start: int
    method_end: int


@dataclass(frozen=True)
class _MethodDefInfo:
    name: str
    rva: int = 0


@dataclass(frozen=True)
class _TypeRefInfo:
    namespace: str
    name: str


@dataclass(frozen=True)
class _MemberRefInfo:
    name: str
    parent_table: int
    parent_row: int


@dataclass(frozen=True)
class _PanelFontPatchTokens:
    font_size_tails: tuple[bytes, ...]
    helper_calls: tuple[bytes, ...]


@dataclass(frozen=True)
class _PanelLayoutPatchTokens:
    style_length_tails: tuple[bytes, ...]
    fixed_item_height_calls: tuple[bytes, ...]


def _safe_zip_members(archive: zipfile.ZipFile) -> list[zipfile.ZipInfo]:
    members: list[zipfile.ZipInfo] = []
    total = 0
    for member in archive.infolist():
        path = PurePosixPath(member.filename.replace("\\", "/"))
        mode = member.external_attr >> 16
        if (
            path.is_absolute()
            or ".." in path.parts
            or not path.parts
            or stat.S_ISLNK(mode)
        ):
            raise RuntimeError(f"payload 包含不安全路径：{member.filename}")
        total += member.file_size
        if total > MAX_EXTRACTED_BYTES:
            raise RuntimeError("payload 解压后超过安全大小限制")
        members.append(member)
    return members


def _extract_payload(payload_zip: Path, staging: Path, expected_version: str) -> None:
    with zipfile.ZipFile(payload_zip) as archive:
        members = _safe_zip_members(archive)
        archive.extractall(staging, members)
    required = (
        staging / "winhttp.dll",
        staging / "doorstop_config.ini",
        staging / "BepInEx/plugins/BazaarPlusPlus.dll",
        staging / "BepInEx/plugins/BazaarPlusPlus.version",
    )
    if not all(path.is_file() for path in required):
        raise RuntimeError("安装 payload 缺少 Steam Deck 所需文件")
    version_file = staging / "BepInEx/plugins/BazaarPlusPlus.version"
    try:
        payload_version = version_file.read_text("utf-8").strip()
    except (OSError, UnicodeDecodeError) as error:
        raise RuntimeError("安装 payload 版本文件无效") from error
    if not payload_version:
        raise RuntimeError("安装 payload 版本为空")
    if normalize_version(payload_version) != expected_version:
        raise RuntimeError(
            f"安装 payload 版本不匹配：预期 {expected_version}，实际 {payload_version}"
        )


def _relative_files(root: Path) -> list[Path]:
    return sorted(
        (path.relative_to(root) for path in root.rglob("*") if path.is_file()),
        key=lambda value: value.as_posix(),
    )


def _assert_safe_destination(game_path: Path, relative: Path) -> Path:
    if relative.is_absolute() or ".." in relative.parts:
        raise RuntimeError(f"拒绝写入不安全路径：{relative}")
    current = game_path
    for part in relative.parts[:-1]:
        current = current / part
        if current.is_symlink():
            raise RuntimeError(f"拒绝写入符号链接目录：{current}")
    return game_path / relative


def _apply_staged_payload(staging: Path, game_path: Path) -> None:
    files = [
        relative
        for relative in _relative_files(staging)
        if relative.as_posix() != BPP_CONFIG
        or not (game_path / relative).exists()
    ]
    staged = {path.as_posix() for path in files}
    stale = [
        Path(path)
        for path in (*BPP_PRIVATE_PATHS, *BPP_DEPENDENCY_PATHS)
        if path != BPP_CONFIG and path not in staged
    ]
    touched = list(dict.fromkeys([*files, *stale]))
    with tempfile.TemporaryDirectory(prefix="bpp-backup-") as backup_name:
        backup = Path(backup_name)
        existing: set[str] = set()
        for relative in touched:
            destination = _assert_safe_destination(game_path, relative)
            if destination.is_file():
                existing.add(relative.as_posix())
                backup_file = backup / relative
                backup_file.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(destination, backup_file)
        try:
            for relative in stale:
                _assert_safe_destination(game_path, relative).unlink(missing_ok=True)
            for relative in files:
                source = staging / relative
                destination = _assert_safe_destination(game_path, relative)
                destination.parent.mkdir(parents=True, exist_ok=True)
                temporary = destination.with_name(destination.name + ".bpp-new")
                temporary.unlink(missing_ok=True)
                shutil.copy2(source, temporary)
                os.replace(temporary, destination)
        except Exception as install_error:
            rollback_error: Optional[Exception] = None
            for relative in files:
                destination = _assert_safe_destination(game_path, relative)
                temporary = destination.with_name(destination.name + ".bpp-new")
                try:
                    temporary.unlink(missing_ok=True)
                except Exception as error:
                    rollback_error = error
            for relative in reversed(touched):
                destination = _assert_safe_destination(game_path, relative)
                backup_file = backup / relative
                try:
                    if relative.as_posix() in existing:
                        destination.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(backup_file, destination)
                    else:
                        destination.unlink(missing_ok=True)
                except Exception as error:
                    rollback_error = error
            if rollback_error is not None:
                raise rollback_error from install_error
            raise


def _dedupe_bytes(values: Iterable[bytes]) -> tuple[bytes, ...]:
    return tuple(dict.fromkeys(values))


def _rva_to_offset(data: bytes, rva: int) -> int:
    pe_offset = struct.unpack_from("<I", data, 0x3C)[0]
    section_count = struct.unpack_from("<H", data, pe_offset + 6)[0]
    optional_header_size = struct.unpack_from("<H", data, pe_offset + 20)[0]
    optional_header = pe_offset + 24
    magic = struct.unpack_from("<H", data, optional_header)[0]
    data_directory = optional_header + (112 if magic == 0x20B else 96)
    section_table = optional_header + optional_header_size
    for index in range(section_count):
        section = section_table + index * 40
        virtual_size = struct.unpack_from("<I", data, section + 8)[0]
        virtual_address = struct.unpack_from("<I", data, section + 12)[0]
        raw_size = struct.unpack_from("<I", data, section + 16)[0]
        raw_pointer = struct.unpack_from("<I", data, section + 20)[0]
        size = max(virtual_size, raw_size)
        if virtual_address <= rva < virtual_address + size:
            return raw_pointer + (rva - virtual_address)
    raise RuntimeError(f"无法解析 RVA：0x{rva:x}")


def _metadata_streams(data: bytes) -> dict[str, bytes]:
    pe_offset = struct.unpack_from("<I", data, 0x3C)[0]
    optional_header = pe_offset + 24
    magic = struct.unpack_from("<H", data, optional_header)[0]
    data_directory = optional_header + (112 if magic == 0x20B else 96)
    cli_rva = struct.unpack_from("<I", data, data_directory + 14 * 8)[0]
    if cli_rva == 0:
        raise RuntimeError("不是 .NET assembly")
    cli_offset = _rva_to_offset(data, cli_rva)
    metadata_rva = struct.unpack_from("<I", data, cli_offset + 8)[0]
    metadata_offset = _rva_to_offset(data, metadata_rva)
    if data[metadata_offset : metadata_offset + 4] != b"BSJB":
        raise RuntimeError("无效的 .NET metadata header")
    version_length = struct.unpack_from("<I", data, metadata_offset + 12)[0]
    offset = metadata_offset + 16 + version_length
    offset = (offset + 3) & ~3
    stream_count = struct.unpack_from("<H", data, offset + 2)[0]
    offset += 4
    streams: dict[str, bytes] = {}
    for _index in range(stream_count):
        stream_offset, stream_size = struct.unpack_from("<II", data, offset)
        offset += 8
        name_end = data.index(b"\0", offset)
        name = data[offset:name_end].decode("ascii")
        offset = (name_end + 4) & ~3
        start = metadata_offset + stream_offset
        streams[name] = data[start : start + stream_size]
    return streams


def _heap_index_size(heap_sizes: int, bit: int) -> int:
    return 4 if heap_sizes & bit else 2


def _table_index_size(row_counts: dict[int, int], table: int) -> int:
    return 4 if row_counts.get(table, 0) >= 0x10000 else 2


def _coded_index_size(row_counts: dict[int, int], tables: tuple[int, ...], tag_bits: int) -> int:
    limit = 1 << (16 - tag_bits)
    return 4 if max((row_counts.get(table, 0) for table in tables), default=0) >= limit else 2


def _read_uint(blob: bytes, offset: int, size: int) -> tuple[int, int]:
    return int.from_bytes(blob[offset : offset + size], "little"), offset + size


def _read_coded_index(
    blob: bytes,
    offset: int,
    size: int,
    tables: tuple[int, ...],
    tag_bits: int,
) -> tuple[tuple[int, int], int]:
    value, offset = _read_uint(blob, offset, size)
    tag = value & ((1 << tag_bits) - 1)
    row = value >> tag_bits
    if tag >= len(tables) or row == 0:
        return (0, 0), offset
    return (tables[tag], row), offset


def _strings_get(strings: bytes, offset: int) -> str:
    if offset <= 0:
        return ""
    end = strings.index(b"\0", offset)
    return strings[offset:end].decode("utf-8", errors="replace")


def _metadata_row_size(
    table: int,
    row_counts: dict[int, int],
    string_size: int,
    guid_size: int,
    blob_size: int,
) -> int:
    idx = lambda t: _table_index_size(row_counts, t)
    coded = lambda tables, bits: _coded_index_size(row_counts, tables, bits)
    type_def_or_ref = coded((2, 1, 27), 2)
    has_constant = coded((4, 8, 23), 2)
    has_custom_attribute = coded(
        (6, 4, 1, 2, 8, 9, 10, 0, 14, 23, 20, 17, 26, 27, 32, 35, 38, 39, 40, 42, 43),
        5,
    )
    has_field_marshal = coded((4, 8), 1)
    has_decl_security = coded((2, 6, 32), 2)
    member_ref_parent = coded((2, 1, 26, 6, 27), 3)
    has_semantics = coded((20, 23), 1)
    method_def_or_ref = coded((6, 10), 1)
    member_forwarded = coded((4, 6), 1)
    implementation = coded((38, 35, 39), 2)
    custom_attribute_type = coded((0, 0, 6, 10, 0), 3)
    resolution_scope = coded((0, 26, 35, 1), 2)
    type_or_method_def = coded((2, 6), 1)
    sizes = {
        0: 2 + string_size + guid_size * 3,
        1: resolution_scope + string_size * 2,
        2: 4 + string_size * 2 + type_def_or_ref + idx(4) + idx(6),
        4: 2 + string_size + blob_size,
        6: 4 + 2 + 2 + string_size + blob_size + idx(8),
        8: 2 + 2 + string_size,
        9: idx(2) + type_def_or_ref,
        10: member_ref_parent + string_size + blob_size,
        11: 2 + has_constant + blob_size,
        12: has_custom_attribute + custom_attribute_type + blob_size,
        13: has_field_marshal + blob_size,
        14: 2 + has_decl_security + blob_size,
        15: 2 + idx(2),
        16: 4 + idx(4),
        17: blob_size,
        18: idx(2) + idx(20),
        20: 2 + string_size + type_def_or_ref,
        21: idx(2) + idx(23),
        23: 2 + string_size + blob_size,
        24: 2 + idx(6) + has_semantics,
        25: idx(2) + method_def_or_ref + method_def_or_ref,
        26: string_size,
        27: blob_size,
        28: 2 + member_forwarded + string_size + idx(26),
        29: 4 + idx(4),
        32: 4 + 2 + 2 + 2 + 2 + 4 + blob_size + string_size * 2,
        35: 2 + 2 + 2 + 2 + 4 + blob_size + string_size * 2 + blob_size,
        38: 4 + string_size + blob_size,
        39: 4 + 4 + string_size + implementation,
        40: 4 + 4 + string_size + implementation,
        41: idx(2) + idx(2),
        42: 2 + 2 + type_or_method_def + string_size,
        43: method_def_or_ref + blob_size,
        44: idx(42) + type_def_or_ref,
    }
    return sizes.get(table, 0)


def _parse_dotnet_metadata(
    data: bytes,
) -> tuple[
    dict[int, _TypeDefInfo],
    dict[int, _MethodDefInfo],
    dict[int, _TypeRefInfo],
    dict[int, _MemberRefInfo],
]:
    streams = _metadata_streams(data)
    tables = streams.get("#~") or streams.get("#-")
    strings = streams.get("#Strings")
    if tables is None or strings is None:
        raise RuntimeError("缺少 .NET metadata stream")
    heap_sizes = tables[6]
    string_size = _heap_index_size(heap_sizes, 0x01)
    guid_size = _heap_index_size(heap_sizes, 0x02)
    blob_size = _heap_index_size(heap_sizes, 0x04)
    valid = struct.unpack_from("<Q", tables, 8)[0]
    offset = 24
    present = [table for table in range(64) if valid & (1 << table)]
    row_counts: dict[int, int] = {}
    for table in present:
        row_counts[table] = struct.unpack_from("<I", tables, offset)[0]
        offset += 4
    table_offsets: dict[int, int] = {}
    for table in present:
        table_offsets[table] = offset
        offset += _metadata_row_size(
            table, row_counts, string_size, guid_size, blob_size
        ) * row_counts[table]

    type_defs: dict[int, _TypeDefInfo] = {}
    method_defs: dict[int, _MethodDefInfo] = {}
    type_refs: dict[int, _TypeRefInfo] = {}
    member_refs: dict[int, _MemberRefInfo] = {}

    if 1 in table_offsets:
        row_size = _metadata_row_size(1, row_counts, string_size, guid_size, blob_size)
        resolution_scope = _coded_index_size(row_counts, (0, 26, 35, 1), 2)
        for row in range(1, row_counts.get(1, 0) + 1):
            row_offset = table_offsets[1] + (row - 1) * row_size + resolution_scope
            name_offset, row_offset = _read_uint(tables, row_offset, string_size)
            namespace_offset, row_offset = _read_uint(tables, row_offset, string_size)
            type_refs[row] = _TypeRefInfo(
                namespace=_strings_get(strings, namespace_offset),
                name=_strings_get(strings, name_offset),
            )

    if 6 in table_offsets:
        row_size = _metadata_row_size(6, row_counts, string_size, guid_size, blob_size)
        for row in range(1, row_counts.get(6, 0) + 1):
            row_offset = table_offsets[6] + (row - 1) * row_size
            rva = struct.unpack_from("<I", tables, row_offset)[0]
            row_offset += 8
            name_offset, row_offset = _read_uint(tables, row_offset, string_size)
            method_defs[row] = _MethodDefInfo(name=_strings_get(strings, name_offset), rva=rva)

    if 2 in table_offsets:
        row_size = _metadata_row_size(2, row_counts, string_size, guid_size, blob_size)
        extends_size = _coded_index_size(row_counts, (2, 1, 27), 2)
        field_index_size = _table_index_size(row_counts, 4)
        method_index_size = _table_index_size(row_counts, 6)
        for row in range(1, row_counts.get(2, 0) + 1):
            row_offset = table_offsets[2] + (row - 1) * row_size + 4
            name_offset, row_offset = _read_uint(tables, row_offset, string_size)
            namespace_offset, row_offset = _read_uint(tables, row_offset, string_size)
            row_offset += extends_size + field_index_size
            method_start, row_offset = _read_uint(tables, row_offset, method_index_size)
            next_offset = table_offsets[2] + row * row_size + 4
            if row < row_counts.get(2, 0):
                next_offset += string_size * 2 + extends_size + field_index_size
                method_end = int.from_bytes(
                    tables[next_offset : next_offset + method_index_size], "little"
                )
            else:
                method_end = row_counts.get(6, 0) + 1
            type_defs[row] = _TypeDefInfo(
                namespace=_strings_get(strings, namespace_offset),
                name=_strings_get(strings, name_offset),
                method_start=method_start,
                method_end=method_end,
            )

    if 10 in table_offsets:
        row_size = _metadata_row_size(10, row_counts, string_size, guid_size, blob_size)
        parent_size = _coded_index_size(row_counts, (2, 1, 26, 6, 27), 3)
        for row in range(1, row_counts.get(10, 0) + 1):
            row_offset = table_offsets[10] + (row - 1) * row_size
            (parent_table, parent_row), row_offset = _read_coded_index(
                tables, row_offset, parent_size, (2, 1, 26, 6, 27), 3
            )
            name_offset, row_offset = _read_uint(tables, row_offset, string_size)
            member_refs[row] = _MemberRefInfo(
                name=_strings_get(strings, name_offset),
                parent_table=parent_table,
                parent_row=parent_row,
            )

    return type_defs, method_defs, type_refs, member_refs


def _bypass_legacy_collection_art_cache(plugin_file: Path, version: str) -> bool:
    """Let the current game's LoadArt run instead of 6.0.0's stale cache prefix.

    The old cache references CardAssetDataSO.cardMaterial, removed by the game.
    A Harmony prefix returning true delegates to the original game implementation,
    including its current asset API and native material ownership/cleanup.
    """
    if normalize_version(version) != "6.0.0":
        return False
    data = bytearray(plugin_file.read_bytes())
    type_defs, methods, type_refs, member_refs = _parse_dotnet_metadata(data)
    legacy_field = any(
        member.name == "cardMaterial"
        and member.parent_table == 1
        and (parent := type_refs.get(member.parent_row)) is not None
        and parent.namespace == "TheBazaar.Assets.Scripts.ScriptableObjectsScripts"
        and parent.name == "CardAssetDataSO"
        for member in member_refs.values()
    )
    if not legacy_field:
        return False
    targets = [
        methods[row]
        for info in type_defs.values()
        if info.namespace == "BazaarPlusPlus.Patches.CollectionPanel"
        and info.name == "CollectionItemLoadArtPatch"
        for row in range(info.method_start, info.method_end)
        if row in methods and methods[row].name == "Prefix"
    ]
    if not targets:
        return False
    if len(targets) != 1 or not targets[0].rva:
        raise RuntimeError("无法定位 6.0.0 图鉴卡图兼容补丁")
    offset = _rva_to_offset(data, targets[0].rva)
    if offset < 0 or offset >= len(data):
        raise RuntimeError("图鉴卡图补丁方法位置无效")
    if data[offset] & 3 == 2:  # Tiny IL header.
        start = offset + 1
        size = data[offset] >> 2
    elif data[offset] & 3 == 3 and offset + 12 <= len(data):
        flags, _stack, size = struct.unpack_from("<HHI", data, offset)
        header_size = (flags >> 12) * 4
        if flags & 8 or header_size < 12:  # No exception sections on this prefix.
            raise RuntimeError("图鉴卡图补丁方法头不受支持")
        start = offset + header_size
    else:
        raise RuntimeError("图鉴卡图补丁方法头无效")
    if size < 2 or start + size > len(data):
        raise RuntimeError("图鉴卡图补丁方法体无效")
    replacement = b"\x17" + b"\x00" * (size - 2) + b"\x2a"  # ldc.i4.1; nops; ret
    if data[start : start + size] == replacement:
        return False
    data[start : start + size] = replacement
    temporary = plugin_file.with_name(plugin_file.name + ".bpp-new")
    temporary.unlink(missing_ok=True)
    temporary.write_bytes(data)
    os.replace(temporary, plugin_file)
    return True


def _panel_font_patch_tokens(data: bytes) -> _PanelFontPatchTokens:
    tails = list(KNOWN_UI_TOOLKIT_FONT_SIZE_TAILS)
    helpers = list(KNOWN_PANEL_FONT_HELPER_CALLS)
    try:
        type_defs, method_defs, type_refs, member_refs = _parse_dotnet_metadata(data)
    except Exception:
        return _PanelFontPatchTokens(
            _dedupe_bytes(tails),
            _dedupe_bytes(helpers),
        )

    # Metadata tokens are local to one assembly build. Legacy tokens may refer
    # to unrelated methods in newer releases, so use them only as a fallback.
    tails = []
    helpers = []

    style_length_tokens = [
        _MetadataToken(10, row)
        for row, member in member_refs.items()
        if member.name == "op_Implicit"
        and member.parent_table == 1
        and (parent := type_refs.get(member.parent_row)) is not None
        and parent.namespace == "UnityEngine.UIElements"
        and parent.name == "StyleLength"
    ]
    font_size_tokens = [
        _MetadataToken(10, row)
        for row, member in member_refs.items()
        if member.name == "set_fontSize"
        and member.parent_table == 1
        and (parent := type_refs.get(member.parent_row)) is not None
        and parent.namespace == "UnityEngine.UIElements"
        and parent.name == "IStyle"
    ]
    for implicit in style_length_tokens:
        for font_size in font_size_tokens:
            tails.append(implicit.call() + b"\x6f" + struct.pack("<I", font_size.value))

    panel_types = {"HistoryPanelUiToolkitView", "CollectionPanelView"}
    helper_names = {"CreateLabel", "StyleCodeCell"}
    for type_info in type_defs.values():
        if type_info.name not in panel_types:
            continue
        for row in range(type_info.method_start, type_info.method_end):
            method = method_defs.get(row)
            if method is not None and method.name in helper_names:
                helpers.append(_MetadataToken(6, row).call())

    return _PanelFontPatchTokens(
        _dedupe_bytes(tails),
        _dedupe_bytes(helpers),
    )


def _panel_layout_patch_tokens(data: bytes) -> _PanelLayoutPatchTokens:
    tails = list(KNOWN_UI_TOOLKIT_LAYOUT_SIZE_TAILS)
    fixed_item_height_calls = list(KNOWN_FIXED_ITEM_HEIGHT_CALLS)
    try:
        _, _, type_refs, member_refs = _parse_dotnet_metadata(data)
    except Exception:
        return _PanelLayoutPatchTokens(
            _dedupe_bytes(tails),
            _dedupe_bytes(fixed_item_height_calls),
        )

    tails = []
    fixed_item_height_calls = []

    style_length_tokens = [
        _MetadataToken(10, row)
        for row, member in member_refs.items()
        if member.name == "op_Implicit"
        and member.parent_table == 1
        and (parent := type_refs.get(member.parent_row)) is not None
        and parent.namespace == "UnityEngine.UIElements"
        and parent.name == "StyleLength"
    ]
    layout_setter_tokens = [
        _MetadataToken(10, row)
        for row, member in member_refs.items()
        if member.name in {"set_height", "set_minHeight", "set_maxHeight"}
        and member.parent_table == 1
        and (parent := type_refs.get(member.parent_row)) is not None
        and parent.namespace == "UnityEngine.UIElements"
        and parent.name == "IStyle"
    ]
    for implicit in style_length_tokens:
        for setter in layout_setter_tokens:
            tails.append(implicit.call() + b"\x6f" + struct.pack("<I", setter.value))

    for row, member in member_refs.items():
        if (
            member.name == "set_fixedItemHeight"
            and member.parent_table == 1
            and (parent := type_refs.get(member.parent_row)) is not None
            and parent.namespace == "UnityEngine.UIElements"
            and parent.name == "BaseVerticalCollectionView"
        ):
            fixed_item_height_calls.append(
                b"\x6f" + struct.pack("<I", _MetadataToken(10, row).value)
            )

    return _PanelLayoutPatchTokens(
        _dedupe_bytes(tails),
        _dedupe_bytes(fixed_item_height_calls),
    )


def _font_size_map(scale: float) -> dict[int, int]:
    return {value: int(value * scale + 0.5) for value in STEAM_DECK_FONT_BASE_SIZES}


def _layout_size_map(scale: float) -> dict[int, float]:
    return {value: value * scale for value in STEAM_DECK_LAYOUT_BASE_SIZES}


def _scale_direct_font_size_constants(
    data: bytearray, scale: float, font_size_tails: Iterable[bytes]
) -> int:
    changes = 0
    sizes = _font_size_map(scale)
    for tail in font_size_tails:
        search_from = 0
        while True:
            tail_index = data.find(tail, search_from)
            if tail_index < 0:
                break
            opcode_index = tail_index - 5
            value_index = tail_index - 4
            if opcode_index >= 0 and data[opcode_index] == 0x22:  # ldc.r4
                value = struct.unpack("<f", data[value_index : value_index + 4])[0]
                if value.is_integer() and int(value) in sizes:
                    scaled = sizes[int(value)]
                    data[value_index : value_index + 4] = struct.pack("<f", scaled)
                    changes += 1
            search_from = tail_index + len(tail)
    return changes


def _scale_style_length_constants(
    data: bytearray, scale: float, style_length_tails: Iterable[bytes]
) -> int:
    changes = 0
    sizes = _layout_size_map(scale)
    for tail in style_length_tails:
        search_from = 0
        while True:
            tail_index = data.find(tail, search_from)
            if tail_index < 0:
                break
            opcode_index = tail_index - 5
            value_index = tail_index - 4
            if opcode_index >= 0 and data[opcode_index] == 0x22:  # ldc.r4
                value = struct.unpack("<f", data[value_index : value_index + 4])[0]
                if value.is_integer() and int(value) in sizes:
                    scaled = sizes[int(value)]
                    data[value_index : value_index + 4] = struct.pack("<f", scaled)
                    changes += 1
            search_from = tail_index + len(tail)
    return changes


def _scale_fixed_item_height_constants(
    data: bytearray, scale: float, fixed_item_height_calls: Iterable[bytes]
) -> int:
    changes = 0
    sizes = _layout_size_map(scale)
    for fixed_item_height_call in fixed_item_height_calls:
        search_from = 0
        while True:
            call_index = data.find(fixed_item_height_call, search_from)
            if call_index < 0:
                break
            window_start = max(0, call_index - 32)
            candidate_index: Optional[int] = None
            for index in range(call_index - 5, window_start - 1, -1):
                if data[index] != 0x22:  # ldc.r4
                    continue
                value = struct.unpack("<f", data[index + 1 : index + 5])[0]
                if value.is_integer() and int(value) in sizes:
                    candidate_index = index + 1
                    break
            if candidate_index is not None:
                value = struct.unpack("<f", data[candidate_index : candidate_index + 4])[0]
                scaled = sizes[int(value)]
                data[candidate_index : candidate_index + 4] = struct.pack("<f", scaled)
                changes += 1
            search_from = call_index + len(fixed_item_height_call)
    return changes


def _scale_helper_font_size_arguments(
    data: bytearray, scale: float, helper_calls: Iterable[bytes]
) -> int:
    changes = 0
    sizes = _font_size_map(scale)
    for helper_call in helper_calls:
        search_from = 0
        while True:
            call_index = data.find(helper_call, search_from)
            if call_index < 0:
                break
            window_start = max(0, call_index - 32)
            candidate_index: Optional[int] = None
            for index in range(call_index - 2, window_start - 1, -1):
                if data[index] == 0x1F and data[index + 1] in sizes:
                    candidate_index = index + 1
                    break
            if candidate_index is not None:
                data[candidate_index] = sizes[data[candidate_index]]
                changes += 1
            search_from = call_index + len(helper_call)
    return changes


def _font_scale_for_preset(preset: str) -> float:
    try:
        return STEAM_DECK_FONT_SIZE_PRESETS[preset]
    except KeyError as error:
        raise RuntimeError("无效的面板字号设置") from error


def _scale_steam_deck_panel_font_sizes(plugin_file: Path, preset: str) -> int:
    font_scale = _font_scale_for_preset(preset)
    direct_font_scale = STEAM_DECK_DIRECT_FONT_SIZE_PRESETS[preset]
    layout_scale = STEAM_DECK_LAYOUT_SIZE_PRESETS[preset]
    if font_scale == 1.0:
        return 0
    data = bytearray(plugin_file.read_bytes())
    font_tokens = _panel_font_patch_tokens(data)
    layout_tokens = _panel_layout_patch_tokens(data)
    changes = _scale_direct_font_size_constants(
        data, direct_font_scale, font_tokens.font_size_tails
    )
    changes += _scale_helper_font_size_arguments(
        data, font_scale, font_tokens.helper_calls
    )
    changes += _scale_style_length_constants(
        data, layout_scale, layout_tokens.style_length_tails
    )
    changes += _scale_fixed_item_height_constants(
        data, layout_scale, layout_tokens.fixed_item_height_calls
    )
    if changes == 0:
        return 0
    temporary = plugin_file.with_name(plugin_file.name + ".bpp-new")
    temporary.unlink(missing_ok=True)
    temporary.write_bytes(data)
    os.replace(temporary, plugin_file)
    return changes


def _section_name(line: str) -> Optional[str]:
    stripped = line.strip()
    if len(stripped) >= 2 and stripped.startswith("[") and stripped.endswith("]"):
        return stripped[1:-1].strip()
    return None


def _config_key(line: str) -> Optional[str]:
    stripped = line.lstrip()
    if not stripped or stripped.startswith("#"):
        return None
    key, separator, _value = line.partition("=")
    if not separator:
        return None
    return key.strip()


def _set_config_value(
    contents: str, section: str, key: str, value: str, block: Iterable[str]
) -> str:
    lines = contents.splitlines()
    target_section = section.casefold()
    target_key = key.casefold()
    section_start: Optional[int] = None
    section_end = len(lines)
    key_index: Optional[int] = None
    current_section: Optional[str] = None

    for index, line in enumerate(lines):
        header = _section_name(line)
        if header is not None:
            if current_section == target_section and section_end == len(lines):
                section_end = index
            current_section = header.casefold()
            if current_section == target_section and section_start is None:
                section_start = index
                section_end = len(lines)
            continue
        if (
            current_section == target_section
            and key_index is None
            and (_config_key(line) or "").casefold() == target_key
        ):
            key_index = index

    if key_index is not None:
        lines[key_index] = f"{key} = {value}"
    elif section_start is not None:
        insert_at = section_end
        additions = list(block)
        if insert_at > 0 and lines[insert_at - 1].strip():
            additions.insert(0, "")
        lines[insert_at:insert_at] = additions
    else:
        if lines and lines[-1].strip():
            lines.append("")
        lines.extend((f"[{section}]", "", *block))

    return "\n".join(lines) + "\n"


def _apply_steam_deck_ui_defaults(game_path: Path) -> None:
    config_path = _assert_safe_destination(game_path, Path(BPP_CONFIG))
    if config_path.is_symlink():
        raise RuntimeError("拒绝写入符号链接形式的 BazaarPlusPlus 配置文件")
    try:
        contents = config_path.read_text("utf-8") if config_path.exists() else ""
    except UnicodeDecodeError as error:
        raise RuntimeError("BazaarPlusPlus 配置文件不是有效的 UTF-8 文本") from error
    updated = _set_config_value(
        contents,
        STEAM_DECK_UI_SECTION,
        STEAM_DECK_UI_FONT_KEY,
        STEAM_DECK_UI_FONT_VALUE,
        STEAM_DECK_UI_FONT_BLOCK,
    )
    if updated == contents:
        return
    config_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = config_path.with_name(config_path.name + ".bpp-new")
    temporary.unlink(missing_ok=True)
    temporary.write_text(updated, "utf-8")
    os.replace(temporary, config_path)


def _third_party_plugins(game_path: Path) -> bool:
    plugins = game_path / "BepInEx/plugins"
    if not plugins.is_dir():
        return False
    owned = {
        Path(path).name.casefold()
        for path in (*BPP_PRIVATE_PATHS, *BPP_DEPENDENCY_PATHS)
    }
    owned.add(".gitkeep")
    return any(child.name.casefold() not in owned for child in plugins.iterdir())


def _remove_paths(game_path: Path, paths: Iterable[str]) -> None:
    for relative_text in paths:
        destination = _assert_safe_destination(game_path, Path(relative_text))
        if destination.is_dir():
            shutil.rmtree(destination)
        else:
            destination.unlink(missing_ok=True)
    for relative_text in ("BepInEx/config", "BepInEx/plugins", "BepInEx"):
        directory = game_path / relative_text
        try:
            directory.rmdir()
        except OSError:
            pass


class Installer:
    def __init__(self, releases: ReleaseSource) -> None:
        self._releases = releases

    def install(
        self,
        release: Release,
        game_path: Path,
        runtime_dir: Path,
        progress: ProgressReporter,
        panel_font_size: str = "medium",
    ) -> None:
        runtime_dir.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(
            prefix="bpp-install-", dir=runtime_dir
        ) as temporary_name:
            temporary = Path(temporary_name)
            payload = self._releases.acquire_payload(release, temporary, progress)
            staging = temporary / "staging"
            staging.mkdir()
            progress("校验安装内容", 82)
            _extract_payload(payload, staging, release.version)
            _bypass_legacy_collection_art_cache(staging / BPP_PLUGIN, release.version)
            progress("应用 Steam Deck 面板字号设置", 86)
            _scale_steam_deck_panel_font_sizes(staging / BPP_PLUGIN, panel_font_size)
            progress("写入游戏目录", 90)
            _apply_staged_payload(staging, game_path)
            progress("应用 Steam Deck UI 适配", 96)
            _apply_steam_deck_ui_defaults(game_path)
        progress("安装完成", 100)

    def uninstall(self, game_path: Path) -> None:
        paths = list(BPP_PRIVATE_PATHS)
        if not _third_party_plugins(game_path):
            paths.extend(BPP_DEPENDENCY_PATHS)
        _remove_paths(game_path, paths)

    def reset_data(self, game_path: Path) -> None:
        paths = [game_path / name for name in (DATA_DIRECTORY, LEGACY_DATA_DIRECTORY)]
        if any(path.is_symlink() for path in paths):
            raise RuntimeError("拒绝删除符号链接形式的数据目录")
        for data_path in paths:
            shutil.rmtree(data_path, ignore_errors=True)

    def installed_version(self, game_path: Path) -> Optional[str]:
        version_file = game_path / "BepInEx/plugins/BazaarPlusPlus.version"
        plugin_file = game_path / "BepInEx/plugins/BazaarPlusPlus.dll"
        if not plugin_file.is_file():
            return None
        try:
            version = version_file.read_text("utf-8").strip()
            return version or "未知"
        except OSError:
            return "未知"

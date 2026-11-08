# Collection card art compatibility fix

Evidence from the user's Steam Deck LogOutput.log: repeated
`collection_panel.card.bind_degraded`, `native_preview_runtime_failed`,
`System.MissingFieldException: UnityEngine.Material ...CardAssetDataSO.cardMaterial`,
from CollectionItemLoadArtPatch.LoadArtFromCache. Installed version is 6.0.0.prod.

Root cause: upstream 6.0.0 replaces the game's LoadArt with a cache implementation
compiled against a removed game field. The current font patch does not modify these methods.

Plan:
- [x] Regressions first: locate exactly the 6.0.0 CollectionItemLoadArtPatch.Prefix,
  preserve all bytes outside its IL body, use native loading, reject unsupported headers.
- [x] Read MethodDef RVAs from existing metadata parser. Rewrite only that prefix to
  return true, allowing Harmony to call the current game's native loader. Restrict to
  known upstream 6.0.0 with the legacy cardMaterial reference; preserve cache-free
  native material ownership and cleanup behavior.
- [x] Run unit tests and actual official 6.0.0 payload integration for every font preset.
- [x] Build wrapper 0.3.1 and independently review the patch.
- [x] After the user exits the game, back up the current DLL, apply the same targeted
  repair through FriendDeck, and verify its bytes. Ask user to reopen the collection
  and check logs again. Do not change saved data.

Tradeoff: bypassing the incompatible cache prioritizes correct game-native loading;
large collection browsing may use more resources until upstream updates its cache.

Verification: 47 TypeScript + 84 Python tests; type check, Rollup, ZIP import smoke, and real 6.0.0 payload install/reinstall for all font presets pass. Actual original Prefix starts at RVA 0x9594 (file offset 0x7794), patch changes 61 code bytes and preserves assembly size and metadata. Applying it twice is a no-op.

Independent review: no actionable blockers. Added an explicit integration assertion that the 6.0.0 compatibility patch applies, addressing the review's test-coverage note. No remote DLL was modified during log inspection; the later authorized application is recorded below.

## Steam Deck application
User confirmed the game was closed and authorized applying the repair. FriendDeck showed idle; pgrep found no TheBazaar.exe. Installed DLL matched official original SHA-256 9021d4ff27a751fc8133375d9266bafccded21cad31e999b86aa4dc382447bed. Backed up to game-root `.bpp-backups/card-art-20261108-224817/BazaarPlusPlus.dll`, verified byte equality, then atomically applied the 70-byte Prefix body replacement. Result SHA-256 verified as 927c900b3594f43b9169ff24c59418e6034d4f2d65a50218c594e61700fc44e8. Terminal reported PATCH_OK, exit code 0. No settings or saved data changed. After restarting the game, the user confirmed collection card images display correctly. The installed Decky wrapper itself was not upgraded during this direct DLL repair; wrapper 0.3.1 ZIP is available locally for future reinstall persistence.

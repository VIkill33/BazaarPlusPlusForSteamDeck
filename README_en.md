# BazaarPlusPlus for Steam Deck

[中文](README.md)

This Decky Loader plugin installs, updates, repairs, and removes the BazaarPlusPlus mod for *The Bazaar* on Steam Deck.

The plugin does not bundle the BazaarPlusPlus mod or desktop-installer source. During installation it reads the official BazaarPlusPlus R2 manifest, downloads the latest Windows x86_64 installer, extracts `BepInExSource/BepInEx.zip` with 7-Zip, validates the payload, and writes it into the Steam game directory.

## Requirements

- The Steam version of *The Bazaar* (App ID `1617400`)
- [Decky Loader](https://github.com/SteamDeckHomebrew/decky-loader)
- Network access to the official BazaarPlusPlus release host and GitHub for the first installation

## Installation

1. Install and launch *The Bazaar* at least once, then exit the game completely.
2. Enable ZIP plugin installation in Decky Loader's developer settings.
3. Download or build `BazaarPlusPlus-<version>.zip`.
4. Install the ZIP through Decky and open BazaarPlusPlus in the Quick Access Menu.
5. Select **Install BazaarPlusPlus**.

The plugin adds Proton's required launch option after installation:

```text
WINEDLLOVERRIDES="winhttp=n,b" %command%
```

Existing launch options are preserved where possible. When the mod is removed, the plugin restores the original value if the current options still match the value it managed.

## Features

- Finds the game in Steam libraries on internal storage and SD cards
- Checks the latest remote release
- Installs, updates, or reinstalls BazaarPlusPlus
- Repairs the Steam launch options
- Resets local BazaarPlusPlus data
- Removes the mod while preserving shared dependencies when other BepInEx plugins exist
- Reports download and extraction progress

Exit the game before installing, repairing, resetting, or removing the mod. Deleting the Decky plugin does not remove files already written into the game directory; use **Uninstall mod** in the plugin first.

## Security

The backend:

- Accepts only HTTPS URLs on the official R2 host and expected release paths
- Rejects cross-host redirects and malformed release paths
- Verifies the downloaded 7-Zip tool against a fixed SHA-256 digest
- Limits manifest, download, and extracted payload sizes
- Rejects ZIP path traversal and symbolic links
- Validates required payload files and the payload version
- Applies files through a temporary staging area and rolls back failed writes

## Build from source

Node.js, pnpm 9+, and Python 3.11+ are required.

```bash
pnpm install --frozen-lockfile
pnpm run bundle
```

The installable artifact is written to:

```text
out/BazaarPlusPlus-<version>.zip
```

`pnpm run bundle` runs TypeScript type checking, Python unit tests, and the Rollup build.

## Repository layout

```text
.
├── main.py                    # Decky Python backend
├── src/index.tsx              # Steam Deck Quick Access UI
├── tests/test_decky_backend.py
├── plugin.json                # Decky plugin metadata
├── package.json               # Dependencies and build commands
├── pnpm-lock.yaml             # Reproducible dependency lock
├── rollup.config.js
├── tsconfig.json
└── scripts/build-plugin.sh
```

`dist/`, `out/`, `node_modules/`, and `__pycache__/` are reproducible local artifacts and are not committed.

## License

Released under the [MIT License](LICENSE). Decky Plugin Template-derived portions retain their BSD 3-Clause License notice.

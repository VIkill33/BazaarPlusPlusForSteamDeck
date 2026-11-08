# Steam Deck 6.x Compatibility Implementation Plan

> **For agentic workers:** Execute with superpowers:executing-plans, task by task.

**Goal:** Install the official 6.0.0 mod through the Steam Deck plugin and deliver a verified ZIP.
**Architecture:** Extend only installer URL validation for the official CDN layout; retain current extraction and Deck adapters.
**Tech Stack:** Python, TypeScript, pnpm, Rollup, Decky.
**Spec:** `docs/superpowers/specs/2026-11-08-steamdeck-6x-design.md`

## Global Constraints
- Preserve existing uncommitted work and user configuration.
- Manifest host remains bppinstaller.bazaarplusplus.com; CDN host is cdn.bazaarplusplus.com.
- Wrapper version 0.3.0; upstream mod version 6.0.0.
- No upstream changes or public release.

## Review Focus
- Wrong host or path prefix must fail validation.
- A mismatched version must fail, including CDN redirects.
- Credentials, unexpected ports, query strings and fragments must remain rejected.
- Existing configuration must survive upgrades.
- All size presets must be tested against the real upstream assembly.

### Task 1: Official CDN compatibility
Files: backend/bpp/release.py, tests/backend/test_release.py.
Interface: _validate_installer_url(url: str, expected_version: str) -> None.
- [x] Add parsing and download regressions for the real CDN layout and rejection cases.
- [x] Run Python release tests; observe new valid-CDN cases fail.
- [x] Support exact legacy/CDN layouts with host-specific prefixes.
- [x] Run release tests; require all pass.

### Task 2: Real payload verification and release bundle
Files: package.json, README.md, README_en.md, tests/backend/test_release.py;
installer.py only if a real incompatibility is found.
- [x] Extract real official 6.0.0 payload and verify manifest SHA-256 of installer.
- [x] Exercise fresh install, all font presets, upgrade with saved config, and uninstall in temporary game directories.
- [x] Add regressions first for any observed incompatibility, then fix.
- [x] Set wrapper version 0.3.0 and update documentation.
- [x] Run pnpm run bundle, package smoke test and diff check; deliver ZIP.

## Execution notes
Work on a new branch in the current checkout to preserve the existing uncommitted
adaptation work. Do not commit that pre-existing work on the user's behalf.

## Verification results
- Baseline: 47 TypeScript + 70 Python tests passed.
- New regressions failed before fixes: CDN parse/download, legacy token collisions, V6 component uninstall, V6 data reset.
- Final bundle: 47 TypeScript + 78 Python tests, type check, Rollup and ZIP import smoke passed.
- Real official 6.0.0 full installer SHA-256 matched official downloads manifest.
- Offline integration passed fresh install, reinstallation, config/data preservation, other-mod preservation, uninstall and reset for all three presets.
- Font/layout patch sites: small 0, medium 34, large 34; binary lengths and metadata remained valid.
- Ruling: redesigned 6.x history panel retains official sizing; old UI Toolkit tokens cannot safely apply. This is stated in the plugin UI and both READMEs.
- Physical Steam Deck rendering, controller input and replay execution remain unverified.
- Independent scoped review: no actionable findings; 48 focused tests and real-payload verification passed.

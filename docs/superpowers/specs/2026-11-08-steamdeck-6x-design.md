# Steam Deck compatibility with BazaarPlusPlus 6.x

Approved scope: full compatibility, selected by the user on 2026-11-08.

Use the existing official complete Windows installer workflow. Accept the official
CDN URL layout (`https://cdn.bazaarplusplus.com/installer/<version>/windows-x86_64/updater/<file>.exe`)
while retaining the old official installer host and its exact path layout.
Keep manifest requests restricted to the existing official manifest URL. Keep HTTPS,
version, credentials, port, query, fragment and extraction checks in force.

Verify real 6.0.0 installer payload, installed version, font/layout presets, upgrade,
configuration preservation and uninstall. Fix additional incompatibilities only when
observed. Keep existing uncommitted UI work. Release the Decky wrapper as 0.3.0;
the installed mod retains the upstream 6.0.0 version. Build a local ZIP for delivery.

Alternatives: a managed-only payload would be smaller but does not provide the native
bootstrap for a first install. Retain the complete installer for one consistent path.
Do not publish a release or change the upstream desktop repository.

# HaloCue 1.0 Electron host

The portable entry is Electron 44.5.1. The local backend and MCP worker remain frozen Python executables at the bundle root and share `_internal`. Electron owns the service process and authenticated shutdown, with sandboxed/context-isolated renderers and native Windows title-bar controls. The existing backend data directory is preserved; Electron window/session preferences live in its `electron` subdirectory.

`npm ci` and `npm test` install/test the pinned host tools. For development, set `HALOCUE_BACKEND_EXE` to a matching frozen backend and run `npm start`. Generate the original selected icon with `python tools/build_brand_icon.py` from the repository root.

`node pack.cjs AUDITED_SOURCE PYTHON_BUNDLE FRESH_OUTPUT` packages only the explicit runtime files, verifies every asar entry against staged source, and combines the official Electron runtime with the audited Python bundle. Finalize with the public release tools to scan the combined bundle and generate its manifest, ZIP and checksum. Keep the Electron and Chromium license files.

`electron/startup.json` records times in milliseconds from host startup: Electron ready, window shown, backend spawned/ready, page loaded and workbench ready. These are local observations, without manuscripts, credentials or network telemetry. First launch with empty state differs from a filesystem/antivirus cold start; report measured conditions.

`electron/appearance.json` contains only validated appearance preferences and computed colors. Boot background and native caption colors use this cache before first paint; system mode uses the current OS theme. Preload restores missing origin-scoped appearance keys before `theme.js`, including a busy-port fallback. Existing renderer preferences win. No arbitrary IPC or Node API is exposed.

`HaloCue.exe --no-update --self-test` is an optional native release self-test, enabled only with an explicit `HALOCUE_USER_DATA_DIR` fixture. It verifies real minimize/restore/maximize APIs, records boot/workbench themes, clipboard-write permission and native title-area geometry, captures regular/narrow renderer snapshots, and requests normal application shutdown. Boot capture waits for the compositor only in this test mode; normal startup has no added delay. Snapshots exclude operating-system caption buttons; the API checks are not manual mouse-hit testing.

The self-test also holds the initial works request for one second and captures `restoring.png` / `restoration-self-test.json` before the editor is ready. It checks the canonical icon is loaded, 72 px icon / 21 px title / 56 px header, and matching theme/background/header between host boot and service restoration. This deliberate delay is absent from normal startup; self-test workbench timings are not production benchmarks. Test failures shut down the owned service and exit nonzero without opening an interactive error dialog.

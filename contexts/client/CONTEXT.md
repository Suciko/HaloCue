# Client context

## Responsibility

The desktop client presents three workspaces: narrative production, AI GalGame,
and the MMT phone. It owns interaction state, window lifecycle, presentation
rendering, local project selection, and user-visible errors.

## Invariants

- The client reads and writes the canonical `HaloCueProject` through typed
  adapters; components do not invent a second story state.
- AA and MMT views share story node IDs, character IDs, asset IDs, variables,
  and save checkpoints.
- Preview and offline export start from the same deterministic `SceneDescriptor`.
- AI results are visibly marked as proposals until the user accepts them.

## 1.0 integrated preview

The maintainer selected Electron for the 1.0 integrated desktop entry. The host
under `apps/desktop-client/electron` owns the native window and one frozen local
service process. It presents the existing writing/AA web app and preserves its
data and MCP boundary. See [ADR-0009](../../docs/adr/0009-1.0-electron-host.md).

### Future client

The Tauri/React client will be introduced under `apps/desktop-client`. The first
vertical slice is a local AA playback screen with a switch to the MMT phone view.
The existing 0.9 web UI remains in the root until the 1.x client has a tested
compatibility path.

# Desktop client

The 1.0 integrated preview's Electron host is implemented in [electron](electron/README.md).
It wraps the existing local backend; see ADR-0009 for ownership and lifecycle.

Planned Tauri client for the three workspaces: narrative production, AI
GalGame, and MMT phone. The first slice is local AA playback with a shared MMT
view. Keep UI state behind typed adapters and keep project semantics in
`packages/project-model`.

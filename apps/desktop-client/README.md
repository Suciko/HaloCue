# Desktop client

Client workspaces for narrative production, AI GalGame, and the MMT phone.
`scene-preview` owns the deterministic AA-style renderer. `scene-editor` is the
React/TypeScript HaloCue 1.1 authoring slice: quick editing and the professional
workbench edit one cue-based project store and mount that same preview renderer.
Keep UI state behind typed adapters and project semantics in
`packages/project-model`.

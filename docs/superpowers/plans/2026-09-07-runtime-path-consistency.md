# Runtime paths agree with settings —06-F11/06-F12

Goal: UI must report the same paths operations use, with restart/source provenance.
No runtime exe execution in tests; create placeholder files/synthetic AA directories.

Spine: current UI labels persisted B as active, while resolve_cli prefers envA then
legacy configA. Use one resolution descriptor {path,source,configured,valid,persisted_path}
for settings and execution. Explicit saved setting should win environment/fallback
because the user selected it in the application. Missing saved selected file must
fail closed visibly (not silently choose a different executable). On explicit clear,
fall back to env HALOCUE_SPINE_CLI then SPINE_CLI,legacy AA config,data AA config,
portable discovery; report actual source/path. Preserve existing licensed local-only
render opt-in. No client path bypass or actual binary validation/execution added.

AA: constructor currently only reads persisted workspace if no settings.aa_data.
Environment configA therefore overrides explicitly savedB on restart. Decide and
expose precedence rather than falsely imply persistent switch. Prefer explicit CLI/
environment startup setting as session override for automation, but disclose persisted
and active/source/restart behavior in returned settings and UI. Alternative consistent
savedB priority can be adopted only after validating explicit CLI semantics; never
silently alter scripts' provided paths. Read actual entrypoint callers before choosing.
Both settings paths must show pending restart/override semantics, not mix values.

Tests actual capability/settings/resolver/render call argument samefile; invalid
persistedfailclosed;clear fallback;env and legacy conflict;restart same policy; no
realSpine/AA processes or model. UI preserves existing controls,shows effective path
and override explanation. Separate shared source resolution to avoid duplicated guesses.

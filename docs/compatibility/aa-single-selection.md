# AA single-selection compatibility evidence

- Kind: compatibility fact
- Scope: AA 0.8.8 presentation adapter
- Observed: 2026-09-06
- Status: format/native-instruction evidence; native playback not yet manually verified
- Implementation tracker: https://github.com/Suciko/HaloCue/issues/36

Local-only research inputs: an AA-saved project (`0-0.aap`), IL2CPP type/RVA
metadata, and GameAssembly.dll. No project contents, recovered implementations
or third-party assets are redistributed in this repository. The DLL SHA-256 is
`de295666a237ddfbcf9ae3190ef8a8a4a8d89f303c348f7b93b19de26249b783`.

| Evidence | Observation | Confidence |
| --- | --- | --- |
| AA-saved SelectionNodeData and SelectionNodeData type declaration | `selectionTexts` is a Newtonsoft List of String; inherited fields are Guid, ConnectionsTo, X, Y. No Scripts, NodeName or selectionGroup field. | High, independent serialization and type evidence |
| SelectionNodeData.LoadValues `0x73C980`, SelectionNode.Start `0x774500` | Copy string list and pad to sixteen entries. | High, native instruction flow |
| SelectionNode.get_selectionCount `0x774B90`, aggregation `0x7908C0` | Count outgoing connections, not padded text entries. One outgoing edge means one answer. | High, native instruction flow |
| SelectionNode.PrepareForCompilation `0x7740D0` | Resolve destination groups using the AA compiler-supplied function. | High, native instruction flow |
| SelectionNode.get_beginning `0x774900`; IL2CPP string literals | Format each answer as `[s{0}] {1}`, subsequent answers with a newline. | High, instructions and literal metadata |
| SelectionNode.CheckTo `0x773EC0` | Limit sixteen, reject duplicate links; no Script-only target restriction observed. | High for checks; Sel-to-Sel/Exit playback still manual |
| SetDummyScript `0x7743C0`, GetDummyScriptForNextNode `0x774010` | Preserve inherited stage state for downstream nodes. | High, native instruction flow |
| ScriptNode.get_beginning `0x773980` | Empty Script can return inherited/default dummy, not a guaranteed silent skip. | High; avoid artificial empty Script nodes |

The saved sample has sixteen empty strings and one outgoing edge to an empty
Script. It proves field shape, not valid answer text or successful playback.
The independent HC fixture uses one synthetic answer plus fifteen empty strings
and one outgoing edge; it does not copy the sample's text, IDs or nodes.

HC leaves ordinary ScriptData.selectionGroup at zero. AA owns its compilation
group IDs. Reply/continuation IDs derive from stable source cards. A single
answer continues linearly, including when it is the final line before Exit.
A no-dialogue preparation row carries the original stage change and one-shot
commands once, without repeating teacher text in the normal dialogue panel.

Answer text is not assumed safe merely because JSON can encode it: AA's observed
formatter concatenates the text into its command stream. Newlines, embedded
selection markers and control-like text must be explicitly rejected where their
meaning cannot be preserved. General multi-choice branching is not implemented.
The writing importer must report Sel answers instead of silently claiming a
complete ordinary-dialogue import.

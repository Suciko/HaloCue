# AA Runtime Compatibility Evidence

HaloCue's scene preview implements the observable AA-style presentation
contract independently. Authorized AA research files are read-only inputs;
their C# and IL2CPP declarations are not copied into this repository.

## Stable layout values

| Behavior | Observed value | Evidence |
| --- | ---: | --- |
| Preview render size | 1280 x 720 | `Preview.renderTexture` serialization |
| `Slot_F1` x/z | -925 / -0.90 | `PreviewScene.unity`, Transform `146` |
| `Slot_F2` x/z | -435 / -1.00 | `PreviewScene.unity`, Transform `102` |
| `Slot_F3` x/z | 0 / -1.10 | `PreviewScene.unity`, Transform `124` |
| `Slot_F4` x/z | 435 / -1.05 | `PreviewScene.unity`, Transform `80` |
| `Slot_F5` x/z | 925 / -0.95 | `PreviewScene.unity`, Transform `112` |
| Script container | (0, -832, 0) | `PreviewScene.unity`, Transform `139` |
| Name label | (-1189.9999, 426, 0) | `PreviewScene.unity`, Transform `83` |
| Dialogue label | (-1184, 321, 0) | `PreviewScene.unity`, Transform `79` |
| Separator line | (0, 361, 0) | `PreviewScene.unity`, Transform `123` |
| Text background | (0, 272, 0), -90 deg | `PreviewScene.unity`, Transform `75` |

The preview maps the 2560-wide logical coordinate space to the 1280-wide
render target. This produces the five stable left percentages exported by
`aa-runtime.js`.

## Runtime behavior values

| Behavior | Observed value | Evidence |
| --- | ---: | --- |
| Standby luminance | 0.6 multiplier | `Character.standbyLuminanceMultiplier` |
| Default move duration | 0.5 seconds | `CharacterMoveAnimation` native constructor at RVA `0x798900` |
| Move easing | tweened, not an instantaneous teleport | `CharacterMoveAnimation.CharacterMoveTask` and `TweenDatas` |
| Layer promotion | explicit `SetOnTop` operation | `Character.SetOnTop` native metadata |
| Text animation | queued per-label typewriter | `QueuedTypewriterAnimation` and `TextTypewriterAnimation` |
| Scenario advance | ordered animation queue | `Test.AdvanceScenario`, native RVA `0x724250` |

The C# files generated from IL2CPP contain declaration stubs with empty method
bodies. Their method names, fields and RVAs are useful evidence, but are not a
runnable implementation. HaloCue therefore exposes equivalent `setPos`,
`setLuminance`, `setOnTop`, `setCloseup`, move/fade/hide and queued typewriter
operations from its own JavaScript runtime.

## Provenance boundary

Only synthetic fixtures and user-provided demo assets are committed. AA/BA
game assets, databases, bundles, local absolute paths and recovered source stay
outside the public repository and are resolved through a future local resource
manifest.

# HaloCue Bilibili Intro Video Production Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produce a polished 4:30–5:30 Bilibili introduction video that proves HaloCue can turn a full-length Chinese story chapter into a reviewable AzureArchive production, then converts viewers into beta testers and potential contributors.

**Architecture:** Treat the production as an evidence pipeline: first freeze a clean, reproducible long-story demo; then capture HaloCue and AzureArchive separately; then lock the narration and graphics; finally assemble, verify, and package the video for publication. Version-control only small text artifacts such as scripts, shot lists, captions, and QA reports; keep recordings, audio stems, project files, and exports outside Git.

**Tech Stack:** HaloCue 0.9 Beta branded Windows build, AzureArchive, GPT-SoVITS, Adobe Premiere Pro project workflow, FFmpeg/ffprobe, Markdown production documents, Bilibili desktop uploader.

## Global Constraints

- Product name is always `HaloCue`; the first full brand card reads `HaloCue 0.9 Beta` and `AzureArchive 剧情演出工具`.
- Final runtime is 4:30–5:30; target runtime is 5:00.
- Master video is 1920×1080, 60 fps, H.264 video, AAC 48 kHz audio.
- The first 5 seconds identify HaloCue as an AA creation tool; the first 20 seconds show long-story scale, generation progress, fast AA output, and a normal-speed quality sample.
- AI is described as proposing staging from context; it does not rewrite dialogue and does not directly generate AAP files.
- The final edit includes about 25 seconds of human review and makes the user's final control visible.
- Generation waiting footage and long AA output are compressed; at least two short AA samples remain at 1× speed.
- GPT-SoVITS narration uses a natural, non-character-imitation voice and is disclosed as AI-generated narration.
- Public GitHub code and the group-integrated test build are described separately; no Spine-related distribution claim is published until distribution rights are confirmed.
- Never record or publish API keys, credentials, private paths, personal notifications, user stories not cleared for publication, or unlicensed third-party binaries.
- The mobile version is described only as planned for the next version; no date or unsupported feature list is promised.
- The approved design is `docs/superpowers/specs/2026-08-09-halocue-bilibili-intro-video-design.md`.

## File and Asset Structure

Version-controlled text artifacts:

```text
docs/video/halocue-bilibili-intro/
  narration.md          # Final narration, pronunciation notes, and section durations
  shot-list.md          # Timecoded edit decision list and source clip names
  capture-log.md        # Capture settings, takes, source checksums, and privacy checks
  graphics-copy.md      # On-screen copy, pipeline graphic, title card, and end card
  publish-copy.md       # Bilibili title, description, chapters, tags, and pinned comment
  qa-report.md          # Technical, factual, visual, audio, and privacy sign-off
```

Large local production assets, deliberately outside Git:

```text
D:\桌面\蔚蓝档案二创\HaloCue介绍视频\
  00-project\HaloCue-B站介绍.prproj
  01-input\vol-1-ch-2-demo.txt
  01-input\镜头版-第二章-reference.aap
  02-recordings\halocue\
  02-recordings\azurearchive\
  03-audio\narration-raw\
  03-audio\narration-final\
  03-audio\music-sfx\
  04-graphics\
  05-captions\HaloCue-B站介绍.zh-CN.srt
  06-review\
  07-export\HaloCue-0.9-Beta-Bilibili-1080p60.mp4
  07-export\HaloCue-0.9-Beta-cover-16x10.png
  07-export\HaloCue-0.9-Beta-cover-16x9.png
```

---

### Task 1: Freeze the Demonstration Chapter and Production Workspace

**Files:**
- Create: `D:\桌面\蔚蓝档案二创\HaloCue介绍视频\` and the subdirectories defined above
- Copy from: `D:\桌面\蔚蓝档案二创\恋爱游戏里没有凯伊路线\archives\第一卷第二章_进入状态_约会节奏优化版.txt`
- Copy from: `D:\桌面\蔚蓝档案二创\AA自动写剧本文件\02-最终AA工程\镜头版-第二章.aap`
- Create: `docs/video/halocue-bilibili-intro/capture-log.md`

**Interfaces:**
- Consumes: The approved design and the existing 250-line second-chapter source plus the known-good second-chapter AAP.
- Produces: Immutable demo copies, SHA-256 checksums, a rights/privacy decision, and one stable source identity used by every later task.

- [ ] **Step 1: Create the production folders without touching the original story or AAP**

Run in PowerShell:

```powershell
$videoRoot = 'D:\桌面\蔚蓝档案二创\HaloCue介绍视频'
$folders = @(
  '00-project', '01-input', '02-recordings\halocue',
  '02-recordings\azurearchive', '03-audio\narration-raw',
  '03-audio\narration-final', '03-audio\music-sfx',
  '04-graphics', '05-captions', '06-review', '07-export'
)
New-Item -ItemType Directory -Force -Path $videoRoot | Out-Null
$folders | ForEach-Object {
  New-Item -ItemType Directory -Force -Path (Join-Path $videoRoot $_) | Out-Null
}
```

Expected: all listed directories exist under `D:\桌面\蔚蓝档案二创\HaloCue介绍视频`.

- [ ] **Step 2: Copy the demo inputs under neutral filenames**

```powershell
Copy-Item -LiteralPath 'D:\桌面\蔚蓝档案二创\恋爱游戏里没有凯伊路线\archives\第一卷第二章_进入状态_约会节奏优化版.txt' -Destination 'D:\桌面\蔚蓝档案二创\HaloCue介绍视频\01-input\vol-1-ch-2-demo.txt'
Copy-Item -LiteralPath 'D:\桌面\蔚蓝档案二创\AA自动写剧本文件\02-最终AA工程\镜头版-第二章.aap' -Destination 'D:\桌面\蔚蓝档案二创\HaloCue介绍视频\01-input\镜头版-第二章-reference.aap'
```

Expected: the copied story remains 250 lines and both files are non-empty.

- [ ] **Step 3: Record the frozen inputs and publication decision**

Create `capture-log.md` with:

```markdown
# HaloCue B站介绍视频录制记录

## 冻结输入

- 剧本：`vol-1-ch-2-demo.txt`
- 剧本行数：250
- 参考工程：`镜头版-第二章-reference.aap`
- 剧本 SHA-256：`6BC6B18F63F90F1C06843122A32506F848DB1829274772CD61AE14D2152D4F7F`
- AAP SHA-256：`82CE08E35F2FBD2BEED5DE26AA609B14C41470390CC465B8EA76490A5F3A6C71`

## 公开检查

- 剧情剧透范围：允许公开第二章演示片段
- 角色、背景、声音与骨骼展示：确认允许用于本视频
- API Key、凭据、本机路径和个人通知：禁止入镜
- Spine 相关分发措辞：仅在确认分发权后使用
```

Generate the hashes:

```powershell
Get-FileHash -Algorithm SHA256 -LiteralPath 'D:\桌面\蔚蓝档案二创\HaloCue介绍视频\01-input\vol-1-ch-2-demo.txt','D:\桌面\蔚蓝档案二创\HaloCue介绍视频\01-input\镜头版-第二章-reference.aap'
```

- [ ] **Step 4: Verify the frozen copy**

```powershell
(Get-Content -Encoding UTF8 -LiteralPath 'D:\桌面\蔚蓝档案二创\HaloCue介绍视频\01-input\vol-1-ch-2-demo.txt' | Measure-Object -Line).Lines
Get-Item -LiteralPath 'D:\桌面\蔚蓝档案二创\HaloCue介绍视频\01-input\镜头版-第二章-reference.aap' | Select-Object Length
```

Expected: line count `250`; AAP length greater than `0`.

- [ ] **Step 5: Commit only the capture log**

```powershell
git add -- docs/video/halocue-bilibili-intro/capture-log.md
git commit -m "docs: freeze HaloCue video demo inputs"
```

### Task 2: Pass the HaloCue Brand, Runtime, and Privacy Gate

**Files:**
- Inspect: `.worktrees/halocue-v0.9-beta-release/ui.html`
- Inspect: `.worktrees/halocue-v0.9-beta-release/branding/`
- Modify: `docs/video/halocue-bilibili-intro/capture-log.md`

**Interfaces:**
- Consumes: The branded HaloCue release worktree and frozen demo copy.
- Produces: A tested recording build and a clean-recording checklist. No recording starts until this task passes.

- [ ] **Step 1: Verify the visible brand and version tests**

Run from `.worktrees/halocue-v0.9-beta-release`:

```powershell
python -m pytest tests/test_halocue_meta.py tests/test_branding.py tests/test_brand_assets.py tests/test_launcher.py tests/test_web_setup_status.py -q
```

Expected: all selected tests pass.

- [ ] **Step 2: Verify the local runtime before recording**

```powershell
python launcher.py --check --json
```

Expected: JSON reports `ok: true` and no blocking issue.

- [ ] **Step 3: Confirm the live interface is recordable**

Open the branded build and verify all five conditions manually:

1. Browser title and visible heading read `HaloCue 0.9 Beta`.
2. Visible subtitle reads `AzureArchive 剧情演出工具`.
3. No API Key field contains visible characters.
4. No physical path appears in the viewport.
5. Windows notifications and messaging overlays are disabled.

Add a dated pass/fail block for these five checks to `capture-log.md`.

- [ ] **Step 4: Create an isolated AA demo project**

Use project name `HaloCue视频演示-第二章`; do not overwrite `镜头版-第二章` or any personal production project. Confirm AzureArchive is closed before HaloCue writes the project, then reopen AzureArchive only after generation and installation finish.

- [ ] **Step 5: Commit the gate result**

```powershell
git add -- docs/video/halocue-bilibili-intro/capture-log.md
git commit -m "docs: record HaloCue video capture gate"
```

### Task 3: Lock the Narration and Shot List Before Recording

**Files:**
- Create: `docs/video/halocue-bilibili-intro/narration.md`
- Create: `docs/video/halocue-bilibili-intro/shot-list.md`

**Interfaces:**
- Consumes: The approved five-minute timeline and the frozen second-chapter demo.
- Produces: An 850–1000 Chinese-character narration and a clip-by-clip capture contract used by recording, TTS, editing, and captions.

- [ ] **Step 1: Write the narration to fixed section budgets**

Use this exact structure in `narration.md`:

| Section | Time | Chinese-character budget | Required message |
|---|---:|---:|---|
| Opening | 0:00–0:20 | 35–55 | A whole chapter is being turned into an AA project; identify HaloCue immediately. |
| Pain | 0:20–0:45 | 75–95 | Writing is only the first step; manual staging is the repetitive cost. |
| Import and review | 0:45–1:30 | 135–165 | Import, identify roles/scenes/assets, resolve issues before generation. |
| AI staging | 1:30–2:15 | 130–160 | Scene-based processing, progress saving, continuation, no dialogue rewriting. |
| Human review | 2:15–2:40 | 75–95 | Inspect and change a real proposal; user retains final control. |
| Compile and AA result | 2:40–3:30 | 135–165 | Deterministic compile, install, and compare source text with AA output. |
| Technical explanation | 3:30–4:10 | 120–150 | AI proposes; registered assets constrain; human reviews; compiler emits project. |
| Open source | 4:10–4:35 | 75–95 | GitHub code, group-integrated test build, Spine public-distribution boundary. |
| Call to action | 4:35–5:00 | 75–95 | Join beta, invite developers, mobile next version. |

Include these exact factual sentences or semantically identical wording:

```text
HaloCue 不会改写你的原台词。
AI 也不会直接生成 AAP 文件。
确认之后，再由确定性的编译器生成 AA 工程。
手机版会在下一个版本推出。
```

- [ ] **Step 2: Add pronunciation notes for GPT-SoVITS**

At the end of `narration.md`, specify:

```text
HaloCue：建议读作“哈洛 Q”，全片保持一致。
AzureArchive：建议读作“Azure Archive”，两个词之间停顿 80–120 毫秒。
AAP：逐字母读作“A-A-P”。
Spine：读作英文单词 Spine，不读作拼音。
GPT-SoVITS：只在视频简介披露，不在正文口播。
```

- [ ] **Step 3: Build the shot list with named source clips**

Create `shot-list.md` with one row per timeline range and these exact clip stems:

```text
HC01-long-script-scroll
HC02-generation-timelapse
AA01-fast-montage
AA02-opening-normal-beat
HC03-import-preflight
HC04-role-asset-review
HC05-scene-progress
HC06-human-review
HC07-compile-install
AA03-project-overview
AA04-final-normal-beat
GH01-repository
GR01-group-qr
```

For each row record planned speed, crop, required on-screen copy, expected duration, and whether source audio is used.

- [ ] **Step 4: Check script length and forbidden wording**

```powershell
$script = Get-Content -Raw -Encoding UTF8 'docs/video/halocue-bilibili-intro/narration.md'
$script.Length
rg -n "自动写剧本|AI直接生成AAP|破解|官方授权|百分之百|零错误|完全自动" 'docs/video/halocue-bilibili-intro/narration.md'
```

Expected: narration body is 850–1000 Chinese characters after excluding headings and tables; forbidden wording produces no unreviewed marketing claim.

- [ ] **Step 5: Commit the locked writing artifacts**

```powershell
git add -- docs/video/halocue-bilibili-intro/narration.md docs/video/halocue-bilibili-intro/shot-list.md
git commit -m "docs: lock HaloCue video narration and shots"
```

### Task 4: Capture the HaloCue Workflow

**Files:**
- Create: `D:\桌面\蔚蓝档案二创\HaloCue介绍视频\02-recordings\halocue\HC01-long-script-scroll.mp4`
- Create: `HC02-generation-timelapse.mp4`, `HC03-import-preflight.mp4`, `HC04-role-asset-review.mp4`, `HC05-scene-progress.mp4`, `HC06-human-review.mp4`, `HC07-compile-install.mp4` in the same directory
- Modify: `docs/video/halocue-bilibili-intro/capture-log.md`

**Interfaces:**
- Consumes: Frozen demo input, branded runtime, and locked shot list.
- Produces: Clean 1080p60 HaloCue recordings with visible state changes and no sensitive information.

- [ ] **Step 1: Configure capture once**

Record at 1920×1080, 60 fps, with the browser at 100% zoom. Hide bookmarks, unrelated tabs, desktop icons, taskbar badges, and the Windows notification center. Capture application/system audio on a separate track or disable it; do not capture a microphone.

- [ ] **Step 2: Capture the long-script and import sequence**

Record `HC01-long-script-scroll`, `HC03-import-preflight`, and `HC04-role-asset-review` as separate takes. Hold every important UI state still for at least two seconds so later zooms and subtitles have clean handles.

- [ ] **Step 3: Capture one uninterrupted real generation run**

Record the full generation as a safety master, then note the wall-clock start/end time in `capture-log.md`. Derive `HC02-generation-timelapse` and `HC05-scene-progress` from the master; never fake progress numbers or splice progress from a different chapter.

- [ ] **Step 4: Capture a real review edit and compile/install**

In `HC06-human-review`, open one proposal, change or reject it, and show the resulting state. In `HC07-compile-install`, show validation, compile, and installation into `HaloCue视频演示-第二章`. Close AzureArchive before the write begins.

- [ ] **Step 5: Verify recording properties**

```powershell
Get-ChildItem 'D:\桌面\蔚蓝档案二创\HaloCue介绍视频\02-recordings\halocue\*.mp4' | ForEach-Object {
  ffprobe -v error -select_streams v:0 -show_entries stream=width,height,r_frame_rate -of default=nw=1 $_.FullName
}
```

Expected for every file: `width=1920`, `height=1080`, `r_frame_rate=60/1` or a verified equivalent constant frame rate.

- [ ] **Step 6: Log and commit the capture evidence**

Add take names, durations, capture date, source hash, and privacy-pass result to `capture-log.md`, then commit only the log:

```powershell
git add -- docs/video/halocue-bilibili-intro/capture-log.md
git commit -m "docs: log HaloCue workflow captures"
```

### Task 5: Capture the AzureArchive Evidence

**Files:**
- Create: `D:\桌面\蔚蓝档案二创\HaloCue介绍视频\02-recordings\azurearchive\AA01-fast-montage.mp4`
- Create: `AA02-opening-normal-beat.mp4`, `AA03-project-overview.mp4`, `AA04-final-normal-beat.mp4` in the same directory
- Modify: `docs/video/halocue-bilibili-intro/capture-log.md`

**Interfaces:**
- Consumes: The generated `HaloCue视频演示-第二章` project and reference AAP.
- Produces: One fast montage source, two real-time quality samples, and one proof of the generated AA project structure.

- [ ] **Step 1: Verify the generated project before capturing**

Open `HaloCue视频演示-第二章` in AzureArchive and confirm that the scenes used for capture load without missing characters, black backgrounds, broken audio references, or blocking errors. Record pass/fail in `capture-log.md`.

- [ ] **Step 2: Capture the opening normal-speed beat**

Record 10–15 seconds around an emotionally visible line that includes at least one expression, bubble, or motion change. Keep the source at 1× speed and preserve clean AA sound. Save as `AA02-opening-normal-beat.mp4`.

- [ ] **Step 3: Capture the long-story montage source**

Record at least three scenes and three characters for `AA01-fast-montage.mp4`. Capture at normal speed; apply 2–4× speed only in the editor so the source remains reusable.

- [ ] **Step 4: Capture project proof and a second normal-speed beat**

Use `AA03-project-overview.mp4` to show the generated project and its structure without lingering on unreadable details. Use `AA04-final-normal-beat.mp4` for an 8–12 second later scene with a different background and emotional tone from `AA02`.

- [ ] **Step 5: Verify video and audio streams**

```powershell
Get-ChildItem 'D:\桌面\蔚蓝档案二创\HaloCue介绍视频\02-recordings\azurearchive\*.mp4' | ForEach-Object {
  ffprobe -v error -show_entries stream=index,codec_type,codec_name,width,height,r_frame_rate,sample_rate -of json $_.FullName
}
```

Expected: all files contain 1920×1080 video; `AA02` and `AA04` contain an audio stream.

- [ ] **Step 6: Log and commit the AA capture evidence**

```powershell
git add -- docs/video/halocue-bilibili-intro/capture-log.md
git commit -m "docs: log AzureArchive result captures"
```

### Task 6: Generate and Normalize GPT-SoVITS Narration

**Files:**
- Create: nine raw section WAV files under `D:\桌面\蔚蓝档案二创\HaloCue介绍视频\03-audio\narration-raw\`
- Create: nine normalized WAV files under `D:\桌面\蔚蓝档案二创\HaloCue介绍视频\03-audio\narration-final\`
- Modify: `docs/video/halocue-bilibili-intro/narration.md`

**Interfaces:**
- Consumes: Locked narration sections and pronunciation notes.
- Produces: Section-level 48 kHz PCM narration stems normalized for editing, with approved takes recorded in the narration document.

- [ ] **Step 1: Generate one WAV per narration section**

Use filenames `VO01-opening.wav` through `VO09-call-to-action.wav`. Generate two takes for any sentence containing `HaloCue`, `AzureArchive`, `AAP`, or `Spine`; choose the clearer take and record the selection in `narration.md`.

- [ ] **Step 2: Remove unnatural pauses without changing wording**

Listen at 1× speed. Regenerate clipped consonants, inconsistent names, robotic terminal rises, or pauses longer than 500 ms inside one sentence. Do not solve pronunciation by replacing factual product names with different words.

- [ ] **Step 3: Resample and normalize each selected take**

Normalize every selected raw WAV with matching output names:

```powershell
$rawRoot = 'D:\桌面\蔚蓝档案二创\HaloCue介绍视频\03-audio\narration-raw'
$finalRoot = 'D:\桌面\蔚蓝档案二创\HaloCue介绍视频\03-audio\narration-final'
Get-ChildItem -LiteralPath $rawRoot -Filter 'VO*.wav' | ForEach-Object {
  $outputPath = Join-Path $finalRoot $_.Name
  ffmpeg -y -i $_.FullName -ar 48000 -ac 1 -af "loudnorm=I=-16:TP=-1.5:LRA=7" $outputPath
}
```

Expected: nine matching mono PCM WAV files at 48 kHz, narration around -16 LUFS, true peak at or below -1.5 dBTP.

- [ ] **Step 4: Verify the narration stems**

```powershell
Get-ChildItem 'D:\桌面\蔚蓝档案二创\HaloCue介绍视频\03-audio\narration-final\*.wav' | ForEach-Object {
  ffprobe -v error -show_entries format=duration -show_entries stream=codec_name,sample_rate,channels -of default=nw=1 $_.FullName
}
```

Expected: nine files, PCM codec, `sample_rate=48000`, `channels=1`, no clipped or empty file.

- [ ] **Step 5: Commit the take decisions, not the audio files**

```powershell
git add -- docs/video/halocue-bilibili-intro/narration.md
git commit -m "docs: approve HaloCue narration takes"
```

### Task 7: Build the Rough Cut and Lock Picture

**Files:**
- Create: `D:\桌面\蔚蓝档案二创\HaloCue介绍视频\00-project\HaloCue-B站介绍.prproj`
- Modify: `docs/video/halocue-bilibili-intro/shot-list.md`
- Create: `D:\桌面\蔚蓝档案二创\HaloCue介绍视频\06-review\HaloCue-rough-cut-v1.mp4`

**Interfaces:**
- Consumes: All HaloCue/AA recordings, normalized narration, and locked shot list.
- Produces: A complete 4:30–5:30 rough cut with timing locked before final graphics and subtitles.

- [ ] **Step 1: Create the Premiere project and sequence**

Create sequence `HaloCue-B站介绍-1080p60` at 1920×1080, 60 fps, progressive, 48 kHz audio. Organize bins as `01-HaloCue`, `02-AA`, `03-VO`, `04-Music-SFX`, `05-Graphics`, `06-Sequences`, and `07-Exports`.

- [ ] **Step 2: Assemble the first 20 seconds before the rest**

Use `HC01` for 0:00–0:03, `HC02` for 0:03–0:08, `AA01` for 0:08–0:14 at 2–4× speed, and `AA02` for 0:14–0:20 at 1×. Place the HaloCue logo/name in the corner from frame one. Confirm a viewer can identify the product and AA workflow with audio muted.

- [ ] **Step 3: Assemble the main demonstration against narration**

Follow the approved ranges exactly: pain 0:20–0:45; import/preflight 0:45–1:30; AI staging 1:30–2:15; human review 2:15–2:40; compile/AA result 2:40–3:30. Remove every loading segment without visible state change.

- [ ] **Step 4: Assemble the technical and call-to-action sections**

Reserve 3:30–4:10 for the six-stage pipeline, 4:10–4:35 for GitHub/group version boundaries, and 4:35–5:00 for group QR, developer invitation, and mobile preview.

- [ ] **Step 5: Mix a functional rough audio track**

Keep narration consistently dominant. Mute sped-up AA dialogue. Restore AA source audio for `AA02` and `AA04`; duck background music under narration and real-time AA dialogue.

- [ ] **Step 6: Export and verify the rough cut duration**

```powershell
ffprobe -v error -show_entries format=duration -of default=nw=1:nk=1 'D:\桌面\蔚蓝档案二创\HaloCue介绍视频\06-review\HaloCue-rough-cut-v1.mp4'
```

Expected: duration between 270 and 330 seconds.

- [ ] **Step 7: Record the picture-lock timings and commit**

Update every planned range in `shot-list.md` with its actual in/out time, then:

```powershell
git add -- docs/video/halocue-bilibili-intro/shot-list.md
git commit -m "docs: lock HaloCue intro rough cut"
```

### Task 8: Add Brand Graphics, Captions, Cover, and Publish Copy

**Files:**
- Create: `docs/video/halocue-bilibili-intro/graphics-copy.md`
- Create: `docs/video/halocue-bilibili-intro/publish-copy.md`
- Create: `D:\桌面\蔚蓝档案二创\HaloCue介绍视频\05-captions\HaloCue-B站介绍.zh-CN.srt`
- Create: `D:\桌面\蔚蓝档案二创\HaloCue介绍视频\07-export\HaloCue-0.9-Beta-cover-16x10.png`
- Create: `D:\桌面\蔚蓝档案二创\HaloCue介绍视频\07-export\HaloCue-0.9-Beta-cover-16x9.png`

**Interfaces:**
- Consumes: Picture-locked timeline, approved HaloCue brand assets, and narration.
- Produces: Final on-screen copy, verified subtitles, two safe cover crops, and complete Bilibili metadata.

- [ ] **Step 1: Create the fixed graphics copy**

`graphics-copy.md` must include these exact cards:

```text
Opening corner: HaloCue 0.9 Beta
Brand card: HaloCue 0.9 Beta / AzureArchive 剧情演出工具
Pipeline: 剧情文本 → 分场景理解 → 演出建议 → 人工审查 → 确定性编译 → AA工程
End card: 加入内测 · GitHub开源 · 手机版下个版本推出
Cover: 一整章剧情 → AA工程
```

- [ ] **Step 2: Add graphics with mobile-readable safe areas**

Keep essential text inside the central 80% of the 1920×1080 frame. Use no more than two lines at once and do not cover dialogue bubbles, HaloCue progress state, or the group QR code.

- [ ] **Step 3: Create and manually correct the SRT**

Generate subtitles from the final narration timings, then manually verify every occurrence of `HaloCue`, `AzureArchive`, `AAP`, `Spine`, character names, and version numbers. Keep each subtitle to two lines or fewer and avoid a single cue shorter than 800 ms.

- [ ] **Step 4: Export two cover crops**

Create a 1920×1200 16:10 cover and a 1920×1080 16:9 safe variant. Both use the main copy `一整章剧情 → AA工程`, show HaloCue branding as secondary information, and keep key text inside the intersection of both crops.

- [ ] **Step 5: Write complete Bilibili metadata**

Use this title in `publish-copy.md`:

```text
我做了一个能把整章剧情变成AA工程的工具｜HaloCue 0.9 Beta
```

The description must contain: one-sentence positioning, GitHub link placement, group-join instruction, open-source/Spine boundary, AI-narration disclosure, third-party/unofficial disclaimer, mobile-next-version note, and chapter timestamps matching the final edit. The pinned comment repeats the group and GitHub access paths without making unverifiable promises.

- [ ] **Step 6: Commit text and metadata artifacts**

```powershell
git add -- docs/video/halocue-bilibili-intro/graphics-copy.md docs/video/halocue-bilibili-intro/publish-copy.md
git commit -m "docs: add HaloCue video graphics and publish copy"
```

### Task 9: Finish Audio, Export the Master, and Run Technical QA

**Files:**
- Create: `D:\桌面\蔚蓝档案二创\HaloCue介绍视频\07-export\HaloCue-0.9-Beta-Bilibili-1080p60.mp4`
- Create: `docs/video/halocue-bilibili-intro/qa-report.md`

**Interfaces:**
- Consumes: Picture-locked sequence, final graphics, corrected captions, narration, AA source audio, and cleared music.
- Produces: Upload-ready 1080p60 master and a signed technical/factual/privacy QA report.

- [ ] **Step 1: Finish the audio mix**

Keep narration intelligible on laptop speakers and ordinary headphones. Target the final program near -14 LUFS integrated, true peak at or below -1 dBTP, with music audibly below narration and no sped-up dialogue artifacts.

- [ ] **Step 2: Export the upload master**

Export H.264, 1920×1080, 60 fps, progressive, high profile; use a high-quality VBR target around 20 Mbps and AAC 48 kHz stereo at 320 kbps. Name the file exactly `HaloCue-0.9-Beta-Bilibili-1080p60.mp4`.

- [ ] **Step 3: Verify container, streams, frame rate, and duration**

```powershell
ffprobe -v error -show_entries format=duration,format_name -show_entries stream=index,codec_name,codec_type,width,height,r_frame_rate,sample_rate,channels -of json 'D:\桌面\蔚蓝档案二创\HaloCue介绍视频\07-export\HaloCue-0.9-Beta-Bilibili-1080p60.mp4'
```

Expected: H.264 video, 1920×1080, 60 fps; AAC stereo at 48 kHz; duration 270–330 seconds.

- [ ] **Step 4: Measure final loudness**

```powershell
ffmpeg -i 'D:\桌面\蔚蓝档案二创\HaloCue介绍视频\07-export\HaloCue-0.9-Beta-Bilibili-1080p60.mp4' -filter_complex ebur128=peak=true -f null NUL
```

Expected: integrated loudness approximately -14 LUFS within a practical ±1 LU range and true peak no higher than -1 dBTP. If outside the range, adjust the Premiere mix and re-export rather than normalizing the already-compressed upload master repeatedly.

- [ ] **Step 5: Perform the visual, factual, and privacy passes**

Create `qa-report.md` and mark each item pass/fail:

1. First frame contains HaloCue branding.
2. First 20 seconds contain long script, progress, fast AA, and 1× AA quality evidence.
3. No dialogue is claimed to be AI-written or rewritten.
4. “AI does not directly generate AAP” is stated and supported visually.
5. Human review is visible for about 25 seconds.
6. GitHub and group-integrated version wording matches the approved design.
7. Spine wording was cleared for publication.
8. Mobile is only promised for the next version.
9. No API key, local path, personal notification, private account, or unauthorized asset is visible.
10. QR code scans from a phone at normal playback size.
11. Subtitles match narration and technical names.
12. The complete video is understandable once with sound and once muted.

- [ ] **Step 6: Review representative frames outside the editor**

```powershell
ffmpeg -y -i 'D:\桌面\蔚蓝档案二创\HaloCue介绍视频\07-export\HaloCue-0.9-Beta-Bilibili-1080p60.mp4' -vf "fps=1/10,scale=960:-1,tile=5x6" -frames:v 1 'D:\桌面\蔚蓝档案二创\HaloCue介绍视频\06-review\contact-sheet.jpg'
```

Open the contact sheet and inspect text size, unintended windows, path leaks, and visual repetition. Also watch the first 30 seconds and last 40 seconds at 1× without skipping.

- [ ] **Step 7: Commit the completed QA report**

```powershell
git add -- docs/video/halocue-bilibili-intro/qa-report.md
git commit -m "docs: verify HaloCue Bilibili video master"
```

### Task 10: Upload as a Draft and Complete the Publication Gate

**Files:**
- Read: `docs/video/halocue-bilibili-intro/publish-copy.md`
- Read: `docs/video/halocue-bilibili-intro/qa-report.md`
- Upload: `D:\桌面\蔚蓝档案二创\HaloCue介绍视频\07-export\HaloCue-0.9-Beta-Bilibili-1080p60.mp4`
- Upload: the better-fitting approved cover from `D:\桌面\蔚蓝档案二创\HaloCue介绍视频\07-export\`
- Upload: `D:\桌面\蔚蓝档案二创\HaloCue介绍视频\05-captions\HaloCue-B站介绍.zh-CN.srt`

**Interfaces:**
- Consumes: Upload-ready master, cover, captions, metadata, QR destination, GitHub destination, and passed QA report.
- Produces: A Bilibili draft ready for the user to review and explicitly publish.

- [ ] **Step 1: Confirm time-sensitive destinations immediately before upload**

Open the GitHub destination and group destination from the same computer and a phone. Confirm both are reachable and the QR code resolves to the intended group path. Do not rely on the value used during editing if it has changed.

- [ ] **Step 2: Upload as a draft, not a public post**

Upload the final MP4, cover, and corrected captions. Paste the title, description, tags, and chapter timestamps from `publish-copy.md`. Enable the uploader declaration that explicitly covers AI-generated or AI-assisted voice/narration; if the uploader offers only one general AI-content declaration, enable that declaration.

- [ ] **Step 3: Review the platform transcode**

After processing completes, watch the first 30 seconds, the technical diagram section, both normal-speed AA samples, the QR end card, and the last 10 seconds in the Bilibili preview. Confirm text remains readable and audio stays synchronized after transcoding.

- [ ] **Step 4: Perform the final publication decision**

Publish only after the user confirms all four items: video preview, cover, description/link destinations, and Spine distribution wording. If any item fails, keep the draft private and revise the source asset rather than patching the public description alone.

- [ ] **Step 5: Record the published identifiers after authorization**

After publication, add the BV identifier, publication date, final title, and final runtime to `publish-copy.md`, then commit:

```powershell
git add -- docs/video/halocue-bilibili-intro/publish-copy.md
git commit -m "docs: record HaloCue video publication"
```

## Final Verification Summary

Before declaring the production complete, the executor must provide evidence for all of the following:

- Frozen demo hashes and the 250-line source check.
- Passing branded-build and runtime checks.
- Final narration length and approved pronunciation takes.
- ffprobe results for raw captures and final export.
- Final duration between 270 and 330 seconds.
- Final audio around -14 LUFS with true peak at or below -1 dBTP.
- Passed factual, brand, privacy, rights, QR, subtitle, and mobile-readability checks.
- Bilibili draft preview approval before public publication.

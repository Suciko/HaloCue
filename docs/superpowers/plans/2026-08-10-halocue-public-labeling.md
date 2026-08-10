# HaloCue Public Labeling Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the existing HaloCue GitHub release immediately understandable to Chinese AzureArchive users and provide an exact Android first-screen naming handoff.

**Architecture:** Keep `HaloCue` as the stable brand and all technical identifiers unchanged. Apply the Chinese functional label only to public presentation surfaces, while documenting Android's shorter launcher label and truthful feature boundary separately.

**Tech Stack:** Git, GitHub CLI, Markdown, Android string-resource guidance

## Global Constraints

- The main brand remains exactly `HaloCue`.
- The current Chinese functional label is exactly `AA 剧本自动演出工具`.
- Do not rename `Suciko/HaloCue`, `v0.9.0-beta.1`, release assets, `com.halocue.android`, or `Download/HaloCue/`.
- Do not advertise AI script writing as a current feature.
- Do not claim the Android build automatically imports into AzureArchive or already matches the Windows feature set.

---

### Task 1: GitHub README Presentation

**Files:**
- Modify: public repository `README.md`

**Interfaces:**
- Consumes: Existing HaloCue 0.9 Beta public README and release boundaries.
- Produces: A GitHub landing page whose title and opening paragraph state the current Chinese product category.

- [ ] **Step 1: Clone the public repository into a clean temporary directory**

Run: `git clone https://github.com/Suciko/HaloCue.git <temporary-directory>`

Expected: the clone checks out `main` without local changes.

- [ ] **Step 2: Update the README title and opening description**

Set the title to `# HaloCue｜AA 剧本自动演出工具`. State that the current version takes an existing script, arranges staging cues, keeps a human review step, and compiles an AzureArchive project. Explicitly state that it does not currently generate the script itself.

- [ ] **Step 3: Verify the Markdown diff**

Run: `git diff --check && git diff -- README.md`

Expected: no whitespace errors; only the title and opening positioning copy change.

- [ ] **Step 4: Commit and push**

Run:

```bash
git add README.md
git commit -m "docs: clarify HaloCue product positioning"
git push origin main
```

Expected: GitHub `main` contains the new README commit.

### Task 2: GitHub Metadata And Existing Release

**Files:**
- Modify externally: repository About description
- Modify externally: repository Topics
- Modify externally: release `v0.9.0-beta.1` display title

**Interfaces:**
- Consumes: The exact naming rules in Global Constraints.
- Produces: Searchable GitHub metadata without changing repository or release identity.

- [ ] **Step 1: Update the About description**

Set it to: `HaloCue｜面向 AzureArchive 的 AA 剧本自动演出工具 · Narrative staging and script annotation`.

- [ ] **Step 2: Add accurate repository Topics**

Add: `azurearchive`, `blue-archive`, `narrative-staging`, `script-annotation`, `visual-novel`, `python`.

- [ ] **Step 3: Update the existing release display title**

Set release `v0.9.0-beta.1` title to `HaloCue 0.9 Beta｜AA 剧本自动演出工具`. Do not alter its tag, body, or assets.

- [ ] **Step 4: Verify through the GitHub API**

Read the repository metadata, README, and release. Confirm the description, Topics, README heading, release tag, title, and asset names match the specification.

### Task 3: Android Naming Handoff

**Files:**
- Create: `06-安卓端/docs/安卓首屏命名与定位说明.md`

**Interfaces:**
- Consumes: Current Android 0.3 export-only behavior and the stable identifiers in Global Constraints.
- Produces: A standalone instruction document for the Android implementation agent.

- [ ] **Step 1: Write exact UI copy and identifier rules**

Specify launcher label `HaloCue`, first-screen title `HaloCue`, subtitle `AA 剧本自动演出工具`, and the current Android capability note. List identifiers and paths that must remain unchanged.

- [ ] **Step 2: Define acceptance checks**

Require the launcher name to remain short, the subtitle to be visible without overlap, Android limitations to remain explicit, and existing package/data paths to remain compatible.

- [ ] **Step 3: Review and commit only the handoff document**

Run: `git diff --check -- docs/安卓首屏命名与定位说明.md`

Then commit only that file with message `docs(android): define HaloCue first-screen naming`.

### Task 4: Final Verification

**Files:**
- Verify: public GitHub repository and release
- Verify: `06-安卓端/docs/安卓首屏命名与定位说明.md`

**Interfaces:**
- Consumes: Outputs from Tasks 1 through 3.
- Produces: Evidence that public presentation changed while stable identifiers did not.

- [ ] **Step 1: Confirm public GitHub state**

Use the GitHub API to verify the repository description, Topics, README first lines, release tag and title, and unchanged release asset names.

- [ ] **Step 2: Confirm local repository state**

Show the Android document commit and working-tree status. Confirm unrelated user changes in the desktop repository remain untouched.

- [ ] **Step 3: Report exact outcomes**

Provide the public repository and release links, the Android handoff document path, and the commits created.

# Remote collaboration protocol

The maintainer and collaborator work from different computers. GitHub is the
shared system of record; no local directory is shared or assumed to exist on
both machines.

## Path rules

- Repository paths in Issues, PRs, handoffs, and agent prompts are relative to
  the repository root, for example `packages/contracts/`.
- A machine-local path must be labeled with its owner and machine scope, such as
  `maintainer-local research input`. Use a placeholder like
  `<LOCAL_RESEARCH_ROOT>` in instructions intended for the other computer.
- Never require the collaborator to open a `D:\` or `E:\` path from the
  maintainer's computer. If a file is needed, describe the observable contract,
  synthetic fixture, or authorized acquisition step instead.
- Do not transfer decompiled applications, game assets, model packages, caches,
  or user projects through GitHub. Record provenance and SHA-256 only; each
  developer uses an authorized local copy or synthetic fixtures.

## Start on a new computer

1. Clone `https://github.com/Suciko/HaloCue.git` into any local directory.
2. Read `AGENTS.md`, `CONTEXT-MAP.md`,
   `docs/product-direction-1.x.md`, and
   `docs/agents/long-term-memory.md`.
3. Run `git fetch origin --prune`, inspect the target branch, open PRs, Issues,
   and newest handoff, then create a short-lived branch from the agreed base.
4. Recreate the documented toolchain and run the smallest baseline check. Do
   not assume the other computer's Python, Node, Rust, FFmpeg, GPU, or model
   cache exists locally.

## Handoff between computers

Every handoff must name the remote commit and PR, not just a local folder:

- source branch and target branch;
- exact commit SHA and whether it is pushed;
- changed relative paths and versioned contracts;
- exact commands and results on the sending computer;
- machine-specific prerequisites and whether they are reproducible;
- known issues and the next bounded action;
- decisions that need the other maintainer's review.

The receiving developer fetches the commit and verifies the tests locally. A
green test result on one machine is evidence, not a claim that Windows, GPU,
FFmpeg, or external resources behave identically elsewhere.

## Feedback and conflicts

New ideas go to a GitHub Issue. Implemented slices go to a PR plus handoff.
When both machines edit the same file, preserve both commits and discuss the
conflict in the PR. Never exchange an archive to replace the working tree and
never force-push over the other developer's branch.

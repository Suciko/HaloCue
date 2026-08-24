# Skill proposal workflow

This is the HaloCue equivalent of OpenClaw's Skill Workshop. It gives an agent
a safe way to learn a repeated workflow without allowing it to silently change
the active instructions used by other agents.

## Proposal layout

Create one directory per candidate:

```text
docs/agents/skill-proposals/<skill-name>/
├── proposal.md
└── SKILL.md
```

Use a lowercase, hyphenated name. `proposal.md` is the review record; `SKILL.md`
is a draft that can be copied into `.agents/skills/<skill-name>/` only after
approval.

## Detection threshold

Draft a candidate when at least one condition is true:

- the same ordered workflow was completed in two separate work sessions;
- the same acceptance checklist appears in two handoffs or Issues;
- agents repeatedly miss the same high-value invariant and a procedure can
  prevent the miss;
- a demonstrated UI or tool workflow has stable inputs and observable output.

Do not create a Skill for a one-off decision, a product goal, a vague style
preference, or a copy of external code.

## Required proposal contents

`proposal.md` must contain:

- status: `proposed`, `in-review`, `approved`, `rejected`, or `retired`;
- proposer, date, owning context, and linked Issue/PR/handoffs;
- trigger and non-trigger examples;
- evidence that the workflow repeats or prevents a real defect;
- expected benefit, failure modes, and security/privacy impact;
- license and provenance check for every external reference;
- dry-run/test result and a reviewer checklist;
- the approval PR and the active Skill path, when approved.

The draft `SKILL.md` must have `name` and a concise `description` in YAML
frontmatter. It must use progressive disclosure, imperative steps, explicit
inputs/outputs, and a completion criterion for every step. Keep reusable assets
or scripts beside the Skill and test them in an isolated temporary workspace.

## Review and activation

1. The agent opens a proposal PR; the active `.agents/skills/` tree is unchanged.
2. A maintainer checks scope, trigger precision, stale assumptions, secret/data
   handling, external licenses, and a dry-run result.
3. Proposals affecting product direction, contracts, or shared ownership need
   both collaborators' approval. A local workflow Skill needs its owning
   maintainer's approval.
4. The approved PR copies the draft to `.agents/skills/<skill-name>/SKILL.md`,
   updates `proposal.md` to `approved`, and links the commit.
5. Retire a Skill by marking it `retired`, removing it in a separate PR, and
   linking the replacement or reason. Do not leave two same-named active Skills.

The active Skill never outranks `AGENTS.md`, `CONTEXT-MAP.md`, product direction,
ADR, contracts, tests, or an explicit maintainer decision.

## Template

Copy `docs/agents/skill-proposals/TEMPLATE.md` and rename the directory before
opening a proposal PR.

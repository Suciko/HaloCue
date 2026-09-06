# ADR-0001: Canonical project model

- Status: accepted
- Date: 2026-08-24

## Decision

`HaloCueProject` is the single source of truth for story structure, stable IDs,
characters, assets, variables, AA presentation, MMT presentation, AI settings,
and save state. StoryForge `StudioProject v2` is an adapter/export format.

## Context

AA-style演出 and MMT phone chat must show the same user-authored story without
forking IDs or silently overwriting presentation-specific fields.

## Consequences

Adapters need explicit mappings and migrations. The editor can offer two views
without storing two independent scripts. Existing StoryForge projects require a
versioned import path rather than becoming the canonical format.

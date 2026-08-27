import { describe, expect, it } from "vitest";

import { demoProject } from "./demoProject";
import {
  diagnoseProject,
  inspectProject,
  migratedCueId,
  migrateProject,
  parseProject,
  serializeProject,
} from "./projectCodec";

function legacyProject() {
  return {
    schema_version: "halocue-project/1.0",
    project_id: "project/legacy",
    title: "旧项目",
    characters: [],
    resources: [],
    chapters: [{
      chapter_id: "chapter/one",
      scenes: [{
        scene_id: "scene/one",
        events: [
          { event_id: "event/background", kind: "background" },
          { event_id: "event/dialogue", kind: "dialogue", text: "你好" },
        ],
      }],
    }],
  };
}

describe("ProjectCodec seam", () => {
  it("matches the canonical Python UUID5 migration", () => {
    expect(migratedCueId("event/background")).toBe("cue/37f803204fb058ff9a8030ec2b6b3444");
    expect(migratedCueId("event-0")).toBe("cue/225136241c57560a9256591a029b6420");
  });

  it("migrates legacy flat events without mutating the source", () => {
    const source = legacyProject();
    const migrated = migrateProject(source) as typeof source & { chapters: Array<{ scenes: Array<{ cues: Array<{ cue_id: string }> }> }> };
    expect(source.chapters[0].scenes[0].events).toHaveLength(2);
    expect(migrated.schema_version).toBe("halocue-project/1.1");
    expect(migrated.chapters[0].scenes[0].cues.map((cue) => cue.cue_id)).toEqual([
      "cue/37f803204fb058ff9a8030ec2b6b3444",
      "cue/3a7f5a064c4956adabd8479db21766c7",
    ]);
    expect(parseProject(source)).toEqual(migrated);
  });

  it("reports nested IDs, references, slots, durations and unknown events", () => {
    const project = structuredClone(demoProject) as Record<string, any>;
    project.characters.push(structuredClone(project.characters[0]));
    const event = project.chapters[0].scenes[0].cues[0].events[1];
    event.character_id = "character/missing";
    event.slot = 6;
    event.duration_ms = 0;
    project.chapters[0].scenes[0].cues[0].events.push({ event_id: "event/vendor", kind: "vendor:future" });

    const diagnostics = diagnoseProject(project);
    expect(diagnostics.map((item) => item.code)).toEqual(expect.arrayContaining([
      "project.duplicate_id",
      "project.unresolved_character",
      "project.invalid_slot",
      "project.invalid_duration",
      "project.unknown_event_kind",
    ]));
    expect(diagnostics.find((item) => item.code === "project.unknown_event_kind")?.severity).toBe("warning");
    expect(inspectProject(project).project).toBeNull();
    expect(() => parseProject(project)).toThrow(/invalid HaloCueProject/);
  });

  it("keeps warning-only namespaced events importable and serializes a defensive clone", () => {
    const project = structuredClone(demoProject) as Record<string, any>;
    project.chapters[0].scenes[0].cues[0].events.push({ event_id: "event/vendor", kind: "vendor:future", value: 1 });
    const parsed = parseProject(project);
    parsed.title = "changed outside codec";
    expect(project.title).toBe(demoProject.title);
    expect(JSON.parse(serializeProject(demoProject))).toEqual(demoProject);
    expect(inspectProject(project).diagnostics).toEqual(expect.arrayContaining([
      expect.objectContaining({ code: "project.unknown_event_kind", severity: "warning" }),
    ]));
  });
});

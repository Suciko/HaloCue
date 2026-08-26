import type { CueEvent, HaloCueProject, SceneDescriptor } from "./types";
import { capabilityRegistry, resolveExpressionAnimation, type CapabilityRegistry } from "./capabilities";
import { firstScene } from "./projectStore";

const RENDERABLE = new Set(["background", "dialogue", "enter", "exit", "wait"]);

export function buildDescriptor(
  project: HaloCueProject,
  selectedCueId: string,
  options: { capabilityRegistry?: CapabilityRegistry } = {},
): SceneDescriptor {
  const registry = options.capabilityRegistry || capabilityRegistry;
  const scene = firstScene(project);
  const selectedIndex = Math.max(0, scene.cues.findIndex((cue) => cue.cue_id === selectedCueId));
  const allEvents = scene.cues.slice(0, selectedIndex + 1).flatMap((cue) => cue.events);
  const events = allEvents.filter((event) => RENDERABLE.has(event.kind));
  const characters = new Map(project.characters.map((character) => [character.character_id, character]));
  const resources = new Map(project.resources.map((resource) => [resource.resource_id, resource]));
  const slots: Array<string | null> = [null, null, null, null, null];
  let background: Record<string, unknown> | null = null;
  let initialBackground: Record<string, unknown> | null = null;

  for (const event of events) {
    if (event.kind === "enter" && event.slot) slots[event.slot - 1] = event.character_id || null;
    if (event.kind === "exit" && event.slot) slots[event.slot - 1] = null;
    if (event.kind === "background" && event.resource_id) {
      const resource = resources.get(event.resource_id);
      if (resource) {
        background = {
          resource_id: resource.resource_id,
          logical_key: resource.logical_key,
          aa_key: resource.aa_key,
          preview_uri: resource.preview_uri,
          focus_x: resource.focus_x,
          focus_y: resource.focus_y,
        };
        if (!initialBackground) initialBackground = structuredClone(background);
      }
    }
  }

  const actors = slots.map((characterId, index) => {
    const character = characterId ? characters.get(characterId) : undefined;
    if (!character) {
      return { slot: index + 1, character_id: null, display_name: "", state: "hidden" };
    }
    const actor: Record<string, unknown> = {
      slot: index + 1,
      character_id: character.character_id,
      display_name: character.name,
      dialogue_name: character.dialogue_name,
      club_name: character.club_name,
      avatar_key: character.avatar_key,
      resource_id: character.resource_id,
      stage_media: character.stage_media,
      state: "visible",
    };
    const latestState = [...allEvents].reverse().find((event) => (
      event.kind === "enter"
      && event.slot === index + 1
      && event.character_id === characterId
    ));
    if (character.stage_media) {
      actor.stage_media = {
        ...character.stage_media,
        animation: resolveExpressionAnimation(
          character.character_id,
          latestState?.expression_id,
          character.stage_media.animation,
          character.capability_id,
          registry,
        ),
      };
    }
    return actor;
  });

  const eventProjection = events.map((event): CueEvent => {
    const projected = { ...event };
    if (projected.kind === "background" && projected.resource_id) {
      const resource = resources.get(projected.resource_id);
      if (resource?.preview_uri) projected.preview_uri = resource.preview_uri;
    }
    return projected;
  });

  return {
    schema_version: "scene-descriptor/1.0",
    scene_id: scene.scene_id,
    location_label: scene.title || "场景预览",
    presentation: {
      frame_rate: 30,
      location_mode: "hidden",
      overlay_controls: {
        auto: true,
        menu: true,
        auto_enabled: false,
        auto_label: "自动",
        menu_label: "菜单",
      },
    },
    background,
    initial_background: initialBackground,
    actors,
    initial_actors: actors.map((actor) => ({ ...actor, state: "hidden" })),
    events: eventProjection,
  };
}

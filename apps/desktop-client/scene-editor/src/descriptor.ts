import type { CueEvent, HaloCueProject, SceneDescriptor } from "./types";
import { capabilityRegistry, resolveExpressionAnimation, type CapabilityRegistry } from "./capabilities";
import { projectCueState } from "./cueStateProjection";
import { sceneEventDefinitions } from "./sceneEventRegistry";

// Kept as a compatibility export for callers that need the complete derived set.
export const RENDERABLE_EVENT_KINDS = new Set(
  sceneEventDefinitions().filter((event) => event.descriptor_renderable).map((event) => event.kind),
);

export function buildDescriptor(
  project: HaloCueProject,
  selectedCueId: string,
  options: { capabilityRegistry?: CapabilityRegistry; sceneId?: string } = {},
): SceneDescriptor {
  const registry = options.capabilityRegistry || capabilityRegistry;
  const projection = projectCueState(project, selectedCueId, { sceneId: options.sceneId });
  const { scene } = projection;
  const events = projection.renderableEvents;
  const characters = new Map(project.characters.map((character) => [character.character_id, character]));
  const resources = new Map(project.resources.map((resource) => [resource.resource_id, resource]));
  const backgroundFor = (event: CueEvent | null): Record<string, unknown> | null => {
    const resource = event?.resource_id ? resources.get(event.resource_id) : undefined;
    return resource ? {
      resource_id: resource.resource_id,
      logical_key: resource.logical_key,
      aa_key: resource.aa_key,
      preview_uri: resource.preview_uri,
      focus_x: resource.focus_x,
      focus_y: resource.focus_y,
    } : null;
  };
  const background = backgroundFor(projection.afterCue.backgroundEvent);
  const initialBackgroundEvent = events.find((event) => (
    event.kind === "background" && event.resource_id && resources.has(event.resource_id)
  )) || null;
  const initialBackground = backgroundFor(initialBackgroundEvent);

  const actors = projection.afterCue.slots.map((characterId, index) => {
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
    const latestState = projection.afterCue.actorStateEvents[index];
    for (const key of ["expression_id", "motion_id", "emoticon_id", "focus"]) {
      if (latestState?.[key] !== undefined) actor[key] = latestState[key];
    }
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

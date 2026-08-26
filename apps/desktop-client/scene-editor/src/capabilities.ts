import type {
  CapabilityAdapterValue,
  CapabilityState,
  CapabilityStateKind,
  Character,
  CharacterCapabilities,
} from "./types";

const STABLE_ID = /^[A-Za-z0-9][A-Za-z0-9._:/-]*$/;
const ADAPTER_KEY = /^[a-z0-9][a-z0-9.-]*:[A-Za-z0-9._/-]+$/;

export interface CapabilityRegistry {
  getForCharacter(characterId: string, capabilityId?: string): CharacterCapabilities | undefined;
  statesFor(
    characterId: string | undefined,
    capabilityId: string | undefined,
    kind: CapabilityStateKind,
  ): CapabilityState[];
}

function clone<T>(value: T): T {
  return structuredClone(value);
}

function isAdapterValue(value: unknown): value is CapabilityAdapterValue {
  return value === null
    || typeof value === "string"
    || typeof value === "number"
    || typeof value === "boolean";
}

function isAdapterState(value: unknown): value is Record<string, CapabilityAdapterValue> {
  return !!value
    && typeof value === "object"
    && !Array.isArray(value)
    && Object.keys(value).every((key) => ADAPTER_KEY.test(key))
    && Object.values(value).every(isAdapterValue);
}

function isState(value: unknown): value is CapabilityState {
  if (!value || typeof value !== "object") return false;
  const state = value as Partial<CapabilityState>;
  return typeof state.state_id === "string"
    && STABLE_ID.test(state.state_id)
    && typeof state.label === "string"
    && state.label.trim().length > 0
    && (state.adapter_state === undefined || isAdapterState(state.adapter_state));
}

function isCapability(value: unknown): value is CharacterCapabilities {
  if (!value || typeof value !== "object") return false;
  const record = value as Partial<CharacterCapabilities>;
  return record.schema_version === "character-capabilities/1.0"
    && typeof record.capability_id === "string"
    && STABLE_ID.test(record.capability_id)
    && typeof record.character_id === "string"
    && STABLE_ID.test(record.character_id)
    && (["expression", "motion", "emoticon", "transition"] as const).every((kind) => (
      Array.isArray(record[kind]) && record[kind].every(isState)
    ));
}

export function parseCapabilityRecords(value: unknown): CharacterCapabilities[] {
  const records = Array.isArray(value) ? value : [value];
  if (!records.every(isCapability)) throw new Error("invalid character-capabilities/1.0 records");
  return clone(records);
}

function state(
  stateId: string,
  label: string,
  adapterState?: Record<string, CapabilityAdapterValue>,
): CapabilityState {
  return adapterState
    ? { state_id: stateId, label, adapter_state: adapterState }
    : { state_id: stateId, label };
}

const DEFAULT_STATES: Record<CapabilityStateKind, CapabilityState[]> = {
  expression: [
    state("expression/neutral", "平静", { "aa:animation": "00_default" }),
    state("expression/smile", "微笑", { "aa:animation": "03" }),
    state("expression/serious", "认真", { "aa:animation": "05" }),
  ],
  motion: [
    state("motion/idle", "待机", { "aa:motion": "idle" }),
    state("motion/nod", "点头", { "aa:motion": "nod" }),
    state("motion/appear", "出现", { "aa:motion": "appear" }),
  ],
  emoticon: [
    state("emoticon/none", "无", { "aa:emoticon": "none" }),
    state("emoticon/bulb", "灵光", { "aa:emoticon": "bulb" }),
    state("emoticon/ellipsis", "省略号", { "aa:emoticon": "ellipsis" }),
    state("emoticon/steam", "蒸汽", { "aa:emoticon": "steam" }),
  ],
  transition: [
    state("transition/cut", "直接切换", { "aa:transition": "cut" }),
    state("transition/fade", "淡入淡出", { "aa:transition": "fade" }),
    state("transition/white", "闪白", { "aa:transition": "white" }),
  ],
};

export class MapCapabilityRegistry implements CapabilityRegistry {
  private readonly byCapabilityId = new Map<string, CharacterCapabilities>();
  private readonly byCharacterId = new Map<string, CharacterCapabilities>();

  constructor(records: readonly CharacterCapabilities[] = []) {
    for (const record of records) {
      if (!isCapability(record)) throw new Error("invalid character-capabilities/1.0 record");
      if (this.byCapabilityId.has(record.capability_id)) {
        throw new Error(`duplicate capability_id ${record.capability_id}`);
      }
      this.byCapabilityId.set(record.capability_id, clone(record));
      if (!this.byCharacterId.has(record.character_id)) {
        this.byCharacterId.set(record.character_id, clone(record));
      }
    }
  }

  getForCharacter(characterId: string, capabilityId?: string): CharacterCapabilities | undefined {
    const byCapability = capabilityId ? this.byCapabilityId.get(capabilityId) : undefined;
    if (byCapability?.character_id === characterId) return clone(byCapability);
    const byCharacter = this.byCharacterId.get(characterId);
    return byCharacter ? clone(byCharacter) : undefined;
  }

  statesFor(
    characterId: string | undefined,
    capabilityId: string | undefined,
    kind: CapabilityStateKind,
  ): CapabilityState[] {
    const record = characterId ? this.getForCharacter(characterId, capabilityId) : undefined;
    const states = record?.[kind];
    return clone(states?.length ? states : DEFAULT_STATES[kind]);
  }
}

const DEFAULT_CAPABILITIES: CharacterCapabilities[] = [
  "character/yuuka",
  "character/noa",
  "character/koyuki",
].map((characterId) => ({
  schema_version: "character-capabilities/1.0" as const,
  capability_id: `capability/${characterId.split("/").pop()}/default`,
  character_id: characterId,
  expression: clone(DEFAULT_STATES.expression),
  motion: clone(DEFAULT_STATES.motion),
  emoticon: clone(DEFAULT_STATES.emoticon),
  transition: clone(DEFAULT_STATES.transition),
}));

export const capabilityRegistry: CapabilityRegistry = new MapCapabilityRegistry(DEFAULT_CAPABILITIES);

export function capabilityStatesFor(
  character: Pick<Character, "character_id" | "capability_id"> | undefined,
  kind: CapabilityStateKind,
  currentStateId?: string,
  registry: CapabilityRegistry = capabilityRegistry,
): CapabilityState[] {
  const states = registry.statesFor(character?.character_id, character?.capability_id, kind);
  if (!currentStateId || states.some((item) => item.state_id === currentStateId)) return states;
  return [state(currentStateId, `未注册 · ${currentStateId}`), ...states];
}

export function resolveExpressionAnimation(
  characterId: string,
  stateId: string | undefined,
  fallback: string | undefined,
  capabilityId?: string,
  registry: CapabilityRegistry = capabilityRegistry,
): string | undefined {
  if (!stateId) return fallback;
  const expression = registry.statesFor(characterId, capabilityId, "expression")
    .find((item) => item.state_id === stateId);
  const animation = expression?.adapter_state?.["aa:animation"];
  return typeof animation === "string" ? animation : fallback;
}

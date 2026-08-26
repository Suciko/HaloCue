import { describe, expect, it } from "vitest";

import {
  capabilityStatesFor,
  MapCapabilityRegistry,
  parseCapabilityRecords,
  resolveExpressionAnimation,
} from "./capabilities";
import type { CharacterCapabilities } from "./types";

const customCapabilities: CharacterCapabilities[] = [{
  schema_version: "character-capabilities/1.0",
  capability_id: "capability/custom/default",
  character_id: "character/custom",
  expression: [
    { state_id: "expression/neutral", label: "平静", adapter_state: { "aa:animation": "idle_custom" } },
    { state_id: "expression/glow", label: "发光", adapter_state: { "aa:animation": "glow_custom" } },
  ],
  motion: [],
  emoticon: [],
  transition: [],
}];

describe("character capability registry", () => {
  it("resolves a stable state through an injected adapter record", () => {
    const registry = new MapCapabilityRegistry(customCapabilities);

    expect(resolveExpressionAnimation(
      "character/custom",
      "expression/glow",
      "fallback",
      "capability/custom/default",
      registry,
    )).toBe("glow_custom");
    expect(registry.statesFor("character/custom", "capability/custom/default", "motion"))
      .toEqual(expect.arrayContaining([
        expect.objectContaining({ state_id: "motion/idle" }),
      ]));
  });

  it("keeps an unknown authored state visible while offering registered choices", () => {
    const registry = new MapCapabilityRegistry(customCapabilities);
    const states = capabilityStatesFor(
      { character_id: "character/custom", capability_id: "capability/custom/default" },
      "expression",
      "expression/legacy",
      registry,
    );

    expect(states[0]).toEqual({ state_id: "expression/legacy", label: "未注册 · expression/legacy" });
    expect(states.some((item) => item.state_id === "expression/glow")).toBe(true);
  });

  it("rejects malformed and duplicate capability records at the seam", () => {
    expect(() => new MapCapabilityRegistry([{} as CharacterCapabilities])).toThrow("invalid");
    expect(() => new MapCapabilityRegistry([{
      ...customCapabilities[0],
      expression: [{
        state_id: "expression/bad",
        label: "坏数据",
        adapter_state: { "aa:animation": { invalid: true } as never },
      }],
    }])).toThrow("invalid");
    expect(() => parseCapabilityRecords([{
      ...customCapabilities[0],
      capability_id: "not valid",
    }])).toThrow("invalid");
    expect(() => new MapCapabilityRegistry([...customCapabilities, ...customCapabilities]))
      .toThrow("duplicate capability_id");
    expect(parseCapabilityRecords(customCapabilities)).toEqual(customCapabilities);
    expect(parseCapabilityRecords(customCapabilities[0])).toEqual(customCapabilities);
    expect(() => parseCapabilityRecords({})).toThrow("invalid character-capabilities/1.0");
  });
});

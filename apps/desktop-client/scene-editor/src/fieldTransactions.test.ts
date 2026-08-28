import { describe, expect, it } from "vitest";

import { parseNumericDraft } from "./fieldTransactions";

describe("field transaction parsing", () => {
  it("keeps empty and partial numeric text out of canonical project state", () => {
    expect(parseNumericDraft("")).toBeNull();
    expect(parseNumericDraft("  ")).toBeNull();
    expect(parseNumericDraft("-")).toBeNull();
    expect(parseNumericDraft(".")).toBeNull();
  });

  it("accepts finite decimal and negative values", () => {
    expect(parseNumericDraft("0.35")).toBe(0.35);
    expect(parseNumericDraft("-0.25")).toBe(-0.25);
  });

  it("rejects values outside field constraints", () => {
    expect(parseNumericDraft("-1.01", { min: -1, max: 1 })).toBeNull();
    expect(parseNumericDraft("1.01", { min: -1, max: 1 })).toBeNull();
    expect(parseNumericDraft("1", { min: -1, max: 1 })).toBe(1);
  });
});

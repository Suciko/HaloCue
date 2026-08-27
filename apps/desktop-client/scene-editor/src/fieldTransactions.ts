export function parseNumericDraft(
  draft: string,
  constraints: { min?: number; max?: number } = {},
): number | null {
  if (!draft.trim()) return null;
  const value = Number(draft);
  if (!Number.isFinite(value)) return null;
  if (constraints.min !== undefined && value < constraints.min) return null;
  if (constraints.max !== undefined && value > constraints.max) return null;
  return value;
}

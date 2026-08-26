type StateMap = Record<string, string>;

// Logical adapter values only. The authorized bytes and machine paths remain
// behind the local resource service.
const expressionAnimations: Record<string, StateMap> = {
  "character/yuuka": {
    "expression/neutral": "00_default",
    "expression/smile": "03",
    "expression/serious": "05",
  },
  "character/noa": {
    "expression/neutral": "00_default",
    "expression/smile": "03",
    "expression/serious": "05",
  },
  "character/koyuki": {
    "expression/neutral": "00_default",
    "expression/smile": "03",
    "expression/serious": "05",
  },
};

export function resolveExpressionAnimation(
  characterId: string,
  stateId: string | undefined,
  fallback: string | undefined,
): string | undefined {
  if (!stateId) return fallback;
  return expressionAnimations[characterId]?.[stateId] || fallback;
}

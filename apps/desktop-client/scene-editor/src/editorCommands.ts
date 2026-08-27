export type EditorKeyboardCommand =
  | "save"
  | "undo"
  | "redo"
  | "duplicate-selection"
  | "delete-selection"
  | "move-selection-up"
  | "move-selection-down"
  | "move-selection-start"
  | "move-selection-end";

export type EditorKeyboardInput = {
  key: string;
  ctrlKey?: boolean;
  metaKey?: boolean;
  shiftKey?: boolean;
  altKey?: boolean;
  composing?: boolean;
  textEditing?: boolean;
  eventListActive?: boolean;
};

export function isTextEditingTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  if (target.matches("input, textarea") || target.isContentEditable || target.contentEditable === "true") {
    return true;
  }
  return Boolean(target.closest("[contenteditable]:not([contenteditable='false'])"));
}

export function editorKeyboardCommand(input: EditorKeyboardInput): EditorKeyboardCommand | null {
  if (input.composing) return null;
  const key = input.key.toLowerCase();
  const mod = Boolean(input.ctrlKey || input.metaKey);

  if (mod && !input.altKey && key === "s") return "save";
  if (input.textEditing) return null;

  if (mod && !input.altKey && key === "z") return input.shiftKey ? "redo" : "undo";
  if (mod && !input.altKey && key === "y") return "redo";
  if (!input.eventListActive) return null;

  if (mod && !input.altKey && key === "d") return "duplicate-selection";
  if (!mod && !input.altKey && key === "delete") return "delete-selection";
  if (!input.altKey || mod) return null;

  return {
    arrowup: "move-selection-up",
    arrowdown: "move-selection-down",
    home: "move-selection-start",
    end: "move-selection-end",
  }[key] as EditorKeyboardCommand | undefined ?? null;
}

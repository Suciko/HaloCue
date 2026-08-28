import { describe, expect, it } from "vitest";

import { editorKeyboardCommand, isTextEditingTarget } from "./editorCommands";

describe("editor keyboard commands", () => {
  it("resolves global save and history commands across platforms", () => {
    expect(editorKeyboardCommand({ key: "s", ctrlKey: true })).toBe("save");
    expect(editorKeyboardCommand({ key: "z", metaKey: true })).toBe("undo");
    expect(editorKeyboardCommand({ key: "z", ctrlKey: true, shiftKey: true })).toBe("redo");
    expect(editorKeyboardCommand({ key: "y", ctrlKey: true })).toBe("redo");
  });

  it("resolves selection commands only from the professional event list", () => {
    expect(editorKeyboardCommand({ key: "d", ctrlKey: true, eventListActive: true }))
      .toBe("duplicate-selection");
    expect(editorKeyboardCommand({ key: "Delete", eventListActive: true }))
      .toBe("delete-selection");
    expect(editorKeyboardCommand({ key: "ArrowUp", altKey: true, eventListActive: true }))
      .toBe("move-selection-up");
    expect(editorKeyboardCommand({ key: "End", altKey: true, eventListActive: true }))
      .toBe("move-selection-end");
    expect(editorKeyboardCommand({ key: "d", ctrlKey: true })).toBeNull();
    expect(editorKeyboardCommand({ key: "Delete" })).toBeNull();
  });

  it("does not steal composition or native text-editing commands", () => {
    expect(editorKeyboardCommand({
      key: "z",
      ctrlKey: true,
      textEditing: true,
    })).toBeNull();
    expect(editorKeyboardCommand({
      key: "d",
      ctrlKey: true,
      eventListActive: true,
      textEditing: true,
    })).toBeNull();
    expect(editorKeyboardCommand({
      key: "Delete",
      eventListActive: true,
      composing: true,
    })).toBeNull();
  });

  it("recognizes native text editing targets", () => {
    const input = document.createElement("input");
    const textarea = document.createElement("textarea");
    const editable = document.createElement("div");
    editable.contentEditable = "true";
    expect(isTextEditingTarget(input)).toBe(true);
    expect(isTextEditingTarget(textarea)).toBe(true);
    expect(isTextEditingTarget(editable)).toBe(true);
    expect(isTextEditingTarget(document.createElement("button"))).toBe(false);
  });
});

# Cross-device story file picker design

Date: 2026-08-03
Status: approved direction

## Goal

Replace the current button-list directory modal with a file selection flow that is natural on both desktop and mobile. Users must be able to choose a story stored on the device running the browser or browse files stored on the computer running AA Script Compiler.

## Product model

The entry point presents two clearly separated sources:

- **Choose from this device** is the primary action. It opens the operating system file picker through a browser file input. Windows uses its native dialog; Android and iOS use their native file providers.
- **Browse host computer** is the secondary action. It opens a responsive, Explorer-style browser for files visible to the Python service.

Both sources finish with the same browser-safe result: a display name and an opaque `file_token`. Downstream story opening and analysis continue to consume the token and do not need to know where the file came from.

## Entry interaction

Clicking any existing “选择文件” or “打开剧情文件” command opens a compact source chooser instead of immediately showing the host directory. The chooser contains:

- primary command: `从此设备选择文件`
- secondary command: `浏览运行主机文件`
- accepted formats: `.txt` and `.md`
- a short source explanation only where ambiguity exists

After a successful selection, the chooser closes, the story field displays only the file name, and the existing read-and-review workflow may continue. Canceling either source leaves the current story unchanged.

## Local-device upload

The browser uses `<input type="file" accept=".txt,.md,text/plain,text/markdown">`. The selected file is sent as raw bytes to a dedicated same-origin endpoint with the original file name in a safely encoded request header. Multipart parsing is intentionally avoided because the application uses a small standard-library HTTP server.

The server:

1. rejects names outside `.txt` and `.md`;
2. rejects empty files and files over 10 MiB;
3. validates that the content is decodable text, accepting UTF-8 (with or without BOM) and the project's existing fallback encodings;
4. writes the bytes atomically to an application-owned temporary upload directory;
5. registers that temporary copy in the existing file-token registry;
6. returns only `file_token`, sanitized `name`, and `size`.

Temporary upload files are deleted when their token expires or when the process next performs upload cleanup. Cleanup never follows paths outside the owned upload directory. The UI never receives the temporary physical path.

## Host file browser

The host browser is a work-focused file manager, not a generic page of buttons.

Desktop layout:

- top command bar: back, forward, up, refresh, breadcrumb address, search;
- left navigation: useful allowed roots, drives, recent host folders;
- main details view: name, type, modified time, and size;
- fixed footer: selected file name, `取消`, and primary `打开`;
- folders open on double-click or Enter; files select on click and open on double-click;
- sortable name, modified time, and size columns;
- only compatible story files appear as selectable files.

Mobile layout:

- one-column file list with stable row height and large touch targets;
- navigation locations move into a drawer;
- breadcrumb horizontally scrolls without widening the page;
- search and core navigation remain visible;
- selection and `打开` remain in a sticky footer.

The browser remembers navigation history only for the current modal session. It does not persist physical paths into browser storage.

## Host API and safety

The browse response may describe the current location for navigation, but confirmation uses a server-issued entry token rather than posting an arbitrary physical path back to the service. Directory and file entry tokens are short-lived and process-local.

Allowed traversal is limited to configured host roots. The service canonicalizes every target, rejects symlink or junction escape, applies the format filter server-side, and never permits an entry token minted for one item to select another item. Hidden application internals and backup directories are not elevated as shortcuts.

The current `/api/picker` path-based compatibility route remains temporarily available to existing internal flows but is not used by the new story picker UI.

## States and errors

- Loading shows a stable list skeleton without resizing the dialog.
- An empty folder states that it has no `.txt` or `.md` story files while keeping folder navigation available.
- Upload validation errors use actionable Chinese messages for unsupported type, empty file, excessive size, or unreadable text.
- Host entries changed after listing produce a refresh prompt instead of selecting a different path.
- Network failure preserves the current location and offers retry.
- Escape closes the active layer and restores focus to the command that opened it.

## Accessibility and visual direction

The design follows a restrained Windows utility aesthetic integrated with the existing application, not a visual clone of File Explorer. It uses semantic buttons, listbox/grid selection states, visible keyboard focus, icon buttons with tooltips, and no inline event handlers. Text never becomes vertical or overlaps at 390 px through desktop widths.

Lucide icons already available to the application are used for navigation, folders, documents, search, refresh, and view controls. Directory entries are rows, not rounded text pills or nested cards.

## Testing and acceptance

Automated coverage must prove:

- upload accepts valid `.txt` and `.md` and returns an opaque token;
- upload rejects invalid extension, empty content, oversized content, and undecodable content;
- returned tokens resolve to application-owned copies and response payloads contain no physical paths;
- host browse filters files, returns sortable metadata, and cannot escape allowed roots;
- host selection requires the exact issued entry token;
- the source chooser routes local selection and host browsing into the same story-open flow;
- keyboard selection, cancel, double-click, and stale-entry errors behave deterministically;
- desktop and 390 px mobile layouts have no page overflow or overlapping controls.

Real-browser acceptance covers Windows desktop and a mobile viewport. Screenshots must show the source chooser, populated host details view, selected-file footer, and mobile navigation drawer. The browser console must contain no CSP, 404, or uncaught runtime errors.

## Non-goals

- Managing, renaming, moving, or deleting host files.
- Previewing arbitrary document formats.
- Uploading folders or custom material assets through this story picker.
- Reproducing every Windows Explorer shell extension or context menu.

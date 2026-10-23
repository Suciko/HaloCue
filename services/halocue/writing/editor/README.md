# 1.0 manuscript editor

The browser bundle is built from `src/manuscript-document.js`. ProseMirror owns
document input, selection, clipboard, composition and edit history. The chapter
adapter owns local drafts, explicit saves and inline AI proposal review. The
saved scene block contract is unchanged.

Build with Node.js and npm:

```sh
cd services/halocue/writing/editor
npm ci --ignore-scripts
npm run build
```

Commit `package-lock.json`, the generated `web/manuscript-document.js` and
`web/vendor/manuscript-document/LICENSES.txt`. Runtime assets are local; no CDN
or Node runtime is needed by the writing page.

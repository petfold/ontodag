# Vendored front-end libraries

`preact-htm.module.js` — the [htm](https://github.com/developit/htm)
`preact/standalone` bundle, v3.1.1 (Preact + hooks + htm in one ES module,
13 KB). MIT licensed, © Jason Miller.

Fetched verbatim from `https://unpkg.com/htm@3.1.1/preact/standalone.module.js`
and committed rather than installed, deliberately:

- **No build step.** The page is one `<script type="module">` and this file.
  There is no `node_modules`, no bundler, no CI step, and nothing to rebuild
  before the app runs. A Python project should not need a JavaScript
  toolchain to serve one page.
- **No CDN at runtime.** A demo site that fetches its framework from someone
  else's host fails when they do, and hands them every visitor's IP. This
  also keeps the page servable from a content-addressed store later, which is
  the direction in `docs/plans/WEB_UI.md` §10.

To update: fetch the same URL at a new version, and change the version here.

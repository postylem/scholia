# v0.4 and Beyond — Plan Stubs

**Status:** Stubs — to be developed when the time comes.

---

## v0.4 Candidates

### Edit last comment in thread
Add an "edit" button on the most-recent comment in a thread (regardless of author), so long as it is the last body entry. Things should still feel append-only — you can only revise what you just said, not rewrite history.

**Mechanism:** The append-only JSONL already handles this. To edit: load the annotation, replace `body[-1]["value"]` (and set a `modified` timestamp on that body entry), update the annotation's `modified`, and append the new version. Dedup by ID means the old line is superseded — no edit history stored. New WS message type `edit_body` for the browser, plus a CLI command (`scholia edit <doc.md> <id> "new text"`).

### Resolve should mark as read
Resolving a thread implicitly means you've seen it. The browser `resolve` action and the CLI `scholia resolve` should both mark the thread as read in the state file, so it doesn't show an unread badge on a closed thread.

### Codebase cleanup pass
Sweep through all Python, JS, CSS, and HTML for stale artifacts from rapid development: dead code, misleading variable names, unreachable branches, unused imports, leftover comments. Run coverage to find untested paths. Do this early in v0.4 before adding new features on top of a messy base.

### CLI housekeeping
- `scholia --version` — print version and exit. Single source of truth for version (currently `__init__.py` and `pyproject.toml` are out of sync).
- `scholia` with no arguments — show help or interactive picker, not an error.
- `scholia skill-init` should offer to append gitignore patterns (`*.scholia.state.json` and optionally `*.scholia.jsonl`) to `.gitignore` if one exists in the current directory or repo root.

### In-browser reply
Let the human type replies directly in the sidebar instead of only via CLI. The reply box UI is already there for new comments; extend it to thread replies with WebSocket send.

### MCP server
Package scholia as an MCP server so AI agents get `scholia_list`, `scholia_reply`, `scholia_view` etc. as native tools without needing CLI skill instructions. The document becomes the shared context — no conversation state transfer.

### PyPI publishing
`uv build && uv publish` so `pipx install scholia` works without a git clone. Requires PyPI account setup and possibly a `scholia` name reservation.

### Global config
`~/.config/scholia/config.toml` for defaults: username, theme preference, default port, editor command. Currently these are env vars or CLI flags.

---

## Design Notes

### Why two sidecar files?
Considered merging `.scholia.jsonl` and `.scholia.state.json` into a single file. Decided against it:

- **Write patterns differ**: JSONL is append-only (safe for concurrent writers); state JSON is atomically overwritten. No clean way to unify.
- **Semantics differ**: Annotations are shared content; read/unread state is personal per-viewer.
- **Multi-user**: Multiple users would share annotations but each have their own read state. Separate files make this natural.
- **Selective gitignore**: You might track annotations but not read state, or ignore both.

The cost (two files instead of one) is cosmetic. Revisit only if a real usability problem emerges.

---

## Saved for Later

### Multi-document sessions
Serve multiple docs from one scholia instance. Index page listing active documents, each with its own sidebar.

### Per-project config
`.scholiarc` or `scholia.toml` in project root for project-specific settings (custom CSL, bibliography path, theme overrides).

### Export / import
Export a document + its annotation threads as a single portable archive (zip or self-contained HTML). Import annotations from other formats (Hypothesis, Google Docs comments).

### Collaborative multi-user
Multiple humans annotating the same doc. Would need conflict resolution for simultaneous edits to the JSONL store, and possibly user auth.

### Inline annotations
Alternative to sidebar: render annotations inline as margin notes or interleaved blocks, closer to traditional scholia.

### Custom renderers
Support rendering backends beyond Pandoc (e.g., Quarto, mdx) for projects that already use those toolchains.

# v0.4 and Beyond — Plan Stubs

**Status:** Stubs — to be developed when the time comes.

---

## v0.4 Candidates

### Edit last human comment
**Do first.** Add an "edit" button on the most recent human comment in a thread, but only if there's no AI reply after it (once the AI has responded, the comment is locked). AI responses are never editable from the browser. Needs a new WebSocket message type and a backend handler that rewrites the last body entry.

### MCP server
Package scholia as an MCP server so AI agents get `scholia_list`, `scholia_reply`, `scholia_start` etc. as native tools without needing CLI skill instructions. The document becomes the shared context — no conversation state transfer.

### In-browser reply
Let the human type replies directly in the sidebar instead of only via CLI. The reply box UI is already there for new comments; extend it to thread replies with WebSocket send.

### PyPI publishing
`uv build && uv publish` so `pipx install scholia` works without a git clone. Requires PyPI account setup and possibly a `scholia` name reservation.

### Global config
`~/.config/scholia/config.toml` for defaults: username, theme preference, default port, editor command. Currently these are env vars or CLI flags.

### Delete / edit comments
Allow editing or deleting comment bodies (from browser and CLI). The append-only JSONL format already supports versioning by ID dedup.

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

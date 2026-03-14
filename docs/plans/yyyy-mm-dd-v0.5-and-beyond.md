# v0.5 and Beyond — Plan Stubs

**Status:** Stubs — to be developed when the time comes.

**v0.4.0 shipped:** edit last comment, `--version`, Options menu, resolve-marks-read, graceful Ctrl-C, codebase cleanup, toolbar redesign.

---

## v0.5 Candidates

### In-browser reply
Let the human type replies directly in the sidebar instead of only via CLI. The reply box UI is already there for new comments; extend it to thread replies with WebSocket send. This is the most obvious missing interaction — users expect to be able to reply where they read.

### MCP server
Package scholia as an MCP server so AI agents get `scholia_list`, `scholia_reply`, `scholia_view` etc. as native tools without needing CLI skill instructions. The document becomes the shared context — no conversation state transfer needed.

### PyPI publishing
`uv build && uv publish` so `pip install scholia` / `pipx install scholia` works without a git clone. Requires PyPI account setup and possibly a `scholia` name reservation.

### Global config
`~/.config/scholia/config.toml` for defaults: username, theme preference, default port, editor command. Currently these are env vars or CLI flags.

### Delete comment
Allow deleting a comment (the last body entry, same constraint as edit). Useful for retracting a message. Append-only JSONL handles this the same way as edit — write the annotation with the body entry removed.

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

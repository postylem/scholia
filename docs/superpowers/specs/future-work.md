# Future work

Items noted during development but out of scope for the current release.

## Save As dialog polish

The current "Save as" dialog uses a directory browser built on `/api/list-dir`.
It works but is rough:

- No visual feedback while saving (spinner, disabled button)
- No confirmation when destination already exists (server returns error toast,
  but should show inline confirmation dialog)
- No way to create a new directory from the dialog
- Filename input should validate `.md` extension
- Keyboard navigation within the directory list
- Consider `showSaveFilePicker()` for Chrome users (not cross-browser, so
  keep the current dialog as fallback)

## Browser "Check the scholia" button

When scholia is launched by an AI agent (e.g. Claude via `scholia view`), the
user currently has to switch back to the terminal and say "check the scholia"
to get the agent to review their annotations. A browser button that triggers
this automatically would close the loop.

### Approaches

1. **MCP push** (when MCP server is built) — the scholia MCP server injects
   a message into the agent's conversation. Most native integration.

2. **`/loop` polling** — the agent runs something like
   `/loop 30s scholia list <path> --since <ts>` to auto-check for new
   annotations and respond. Works today with the ralph-loop plugin. The
   browser could show a status indicator ("Auto-reviewing enabled") and
   a pause/resume toggle.

3. **Webhook/callback** — the server calls a Claude Code API endpoint to
   inject a message. No such API exists yet.

### UX sketch

- Button in toolbar or sidebar: "Ask AI to review" / "Check comments"
- If a `/loop` is running: show "Auto-reviewing" indicator with pause/resume
- If no agent connection: show "Copy command" with the `scholia list` invocation
- Notification dot when the agent has responded to annotations

### Prerequisites

- MCP server (planned for v0.7) for approach 1
- Or: just document the `/loop` pattern in the skill file for now

# `scholia mv`, `scholia rm`, and ephemeral stdin mode

**Date:** 2026-03-25
**Scope:** Two new CLI commands + ephemeral cleanup + browser "Save as" button
**Depends on:** stdin view support (already shipped)

## Motivation

After rendering a response with `scholia view -`, there's no clean way to:

1. **Save a keeper** — the temp file sits in `/tmp/` and you have to manually
   copy the `.md` plus its `.scholia.jsonl` and `.scholia.state.json` sidecars.
   If a server is running, it stays pointed at the old path.
2. **Discard a throwaway** — temp files accumulate until the OS cleans `/tmp/`.

Two new CLI commands (`mv`, `rm`) handle the sidecar bundle as a unit, and
ephemeral mode auto-cleans stdin-created temp files on server exit.

## Part 1: `scholia mv`

### Interface

```bash
scholia mv <source.md> <dest.md>
```

Moves the document and its sidecars as a unit:
- `source.md` → `dest.md`
- `source.md.scholia.jsonl` → `dest.md.scholia.jsonl`
- `source.md.scholia.state.json` → `dest.md.scholia.state.json`

Missing sidecars are silently skipped (not every document has annotations).

### Server handoff

If a `scholia view` server is currently watching `source.md`, the move should
transfer the server to the new path without requiring a restart.

**Mechanism: server info in state file + relocate API.**

Server presence is stored in the existing `.scholia.state.json` sidecar under
a `_server` key (underscore prefix avoids collision with `urn:uuid:...`
annotation IDs):

```json
{
  "urn:uuid:a8c0...": {"lastReadAt": "2026-03-25T..."},
  "_server": {"port": 8088, "pid": 12345}
}
```

1. When `scholia view` starts, write `_server` to the state file with the
   port and PID. Remove `_server` on server exit (in a `finally` block).

2. When `scholia mv` runs, load the state file for `source.md`. If `_server`
   is present, POST to `http://127.0.0.1:<port>/api/relocate` with
   `{"to": "<dest.md>"}`.

3. The server's `/api/relocate` handler:
   - Moves all files (doc + sidecars) to the destination.
   - Restarts the file watcher on the new path.
   - Updates the internal `doc_path`.
   - Updates `_server` in the new state file.
   - Broadcasts a `doc_relocate` WebSocket message so the browser updates its
     breadcrumb and any internal path references.
   - Returns `200 OK` with `{"path": "<dest.md>"}`.

4. If no server is running (no `_server` key, or server unreachable),
   `scholia mv` moves the files directly.

### Edge cases

- **Destination exists:** error unless `--force`.
- **Source doesn't exist:** error.
- **Cross-filesystem move:** use `shutil.move` (handles copy+delete fallback).
- **Stale `_server` (server crashed):** if the API call fails (connection
  refused), remove the stale `_server` key and fall back to direct move.

## Part 2: `scholia rm`

### Interface

```bash
scholia rm <doc.md>
scholia rm <doc.md> --force
```

Deletes the document and its sidecars:
- `doc.md`
- `doc.md.scholia.jsonl`
- `doc.md.scholia.state.json`
- `_server` key in state file (cleared if present)

**Without `--force`:** prints the list of files that will be deleted and
prompts for confirmation (`Delete 3 files? [y/N]`).

**With `--force`:** deletes without prompting.

Missing sidecars are silently skipped. If `_server` is present in the state
file, warn: `"Warning: a scholia view server is watching this file."`

## Part 3: Ephemeral mode for stdin

### Behavior

When `scholia view -` creates a temp file, the default behavior is
**ephemeral**: on server exit, delete the temp file and any sidecars that
were created during the session.

```bash
# Ephemeral by default (cleans up on exit)
echo '$$E=mc^2$$' | scholia view -

# Keep the temp file after exit
echo '$$E=mc^2$$' | scholia view - --keep
```

For named files, behavior is always non-ephemeral (never delete the user's
files on exit).

### Implementation

- Add a `--keep` flag to `scholia view` (only meaningful with `-`, ignored
  with a warning otherwise — same pattern as `--title`).
- When serving a stdin-created temp file without `--keep`, register a cleanup
  function in the server's shutdown path that deletes the temp `.md` and any
  `.scholia.jsonl` / `.scholia.state.json` that exist.
- If the user runs `scholia mv` during the session (promoting the temp file
  to a real location), the server's relocate handler clears the ephemeral flag
  so the moved file is NOT deleted on exit.

### Why `--keep` instead of `--ephemeral`

The flag names the override, not the default. Since ephemeral is the default
for stdin, the user says `--keep` to opt out. This avoids the confusing
double-negative of `--no-ephemeral` and reads naturally:
`echo '...' | scholia view - --keep`.

## Part 4: Browser "Save as" button

### UX

Add a "Save as..." option to the browser's Options menu (alongside Export PDF,
theme, etc.). Only shown when viewing a temp file (path starts with the system
temp directory).

1. User clicks "Save as..."
2. A modal text input appears, pre-filled with a suggested path based on the
   document title (e.g., `~/Documents/<title-slug>.md`). The user can edit.
3. On submit, the browser sends a WebSocket message:
   `{type: "save_as", path: "/Users/v/notes/foo.md"}`
4. The server validates the path, calls the same relocate logic as `scholia mv`,
   and responds: `{type: "relocated", path: "/Users/v/notes/foo.md"}`
5. The browser updates the breadcrumb path and clears the "Save as..." option
   from the menu (no longer a temp file).
6. The ephemeral flag is cleared (file won't be deleted on exit).

### Path validation

- Destination must not exist (or modal shows confirmation dialog).
- Destination directory must exist.
- Destination must end in `.md` (or a recognized markdown extension).

## Testing

- **`scholia mv`:** Test moving a doc with sidecars. Test moving with no
  sidecars. Test destination-exists error. Test stale lockfile fallback.
- **`scholia rm`:** Test deleting a doc with sidecars. Test `--force` skips
  prompt. Test with no sidecars.
- **Ephemeral:** Test that stdin-created temp files are deleted on server exit.
  Test that `--keep` preserves them. Test that `scholia mv` during a session
  clears the ephemeral flag.
- **Server state key:** Test `_server` written to state on server start,
  removed on exit, stale `_server` detection.
- **Browser save-as:** Test the WebSocket `save_as` message triggers relocate.
  Test that the option only appears for temp files.

## Non-goals

- No recursive directory moves (`scholia mv dir/ dir2/`).
- No glob support (`scholia rm *.md`).
- No integration with the browser file picker (native OS file dialogs are not
  accessible from a localhost web page without complex workarounds). The text
  input with a suggested path is the pragmatic choice.

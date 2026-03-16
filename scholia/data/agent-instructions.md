---
name: scholia
description: Review and respond to scholia annotations on markdown documents. Use when asked to check comments, review scholia, or respond to annotations.
---

# Scholia — AI Review Instructions

Scholia is a collaborative annotation system for markdown documents. The human writes/edits a `.md` file and adds margin comments via a browser sidebar. You review and reply via CLI.

## Files

- `<doc>.md` — the document (read and edit directly)
- `<doc>.md.scholia.jsonl` — comment store (append-only JSONL). Do NOT edit directly; use the CLI.
- `<doc>.md.scholia.state.json` — read/unread state. Do NOT edit directly.

## CLI Reference

### Reading

```bash
# List open threads with messages and document context (default)
scholia list <doc.md>

# Include resolved threads
scholia list <doc.md> --all

# Filter by date (composes with --all)
scholia list <doc.md> --since 2026-03-10

# Output formats: context (default), messages-only, summary, raw
scholia list <doc.md> --format summary

# Show a single thread (accepts ID prefix — e.g. 'a8c0' instead of full urn:uuid:...)
scholia show <doc.md> <id>
```

### Writing

```bash
# Reply to a thread
scholia reply <doc.md> <id> "Your reply" --author-ai-model "<model>"

# Add a new comment anchored to exact text from the document
scholia comment <doc.md> "exact text to anchor to" "Your comment" --author-ai-model "<model>"

# Edit the last message in a thread
scholia edit <doc.md> <id> "Replacement text"

# Resolve / reopen a thread
scholia resolve <doc.md> <id>
scholia unresolve <doc.md> <id>
```

All writing commands accept `-q`/`--quiet` to suppress confirmation output.
All ID arguments accept a unique prefix (e.g. `a8c0` matches `urn:uuid:a8c086ab-...`).

### Setup

```bash
# Launch live-rendering server (opens browser)
scholia view <doc.md>

# Install AI agent skill file
scholia skill-init
```

## Review Workflow

When asked to review comments, "check the scholia," or equivalent:

1. **Read the document** first. Understand its content, structure, and purpose before looking at any comments — just as an editor would read a manuscript before turning to the margin notes.

2. **List open threads**: `scholia list <doc.md>`. Each thread is shown with:
   - A file location reference (e.g. `doc.md:13:8-28`) — use this to jump back to the source when you need more context than the snippet provides.
   - The section heading it falls under (e.g. `in § Consistency Model`).
   - A few lines of surrounding document text with the anchored selection marked by `^^^^` carets.
   - The full conversation thread.

3. **For each open thread**, decide what's needed:
   - **Question** → reply with an answer. If answering requires understanding context beyond the snippet, read the surrounding passage in the document using the file reference.
   - **Change request** → edit the `.md` file, then reply confirming what you changed.
   - **Acknowledgement** → reply briefly (e.g. "Ack." or "Done.").
   - **Ambiguous** → ask for clarification rather than guessing.

4. **Handle orphaned threads.** If a thread shows `warning: anchor text not found in document (orphaned)`, it means the passage the comment was attached to has been edited or deleted. The original context (prefix/suffix from when the comment was made) is shown, but may be incomplete. If the comment's intent is clear from the thread alone, respond normally. If not, reply asking the human to re-anchor the thread — they can do this in the browser UI by clicking the `?` icon on the orphaned card and selecting new text.

5. **Resolve** threads that are done. Resolved threads are hidden from `scholia list` by default.

## Guidelines

- **Always pass `--author-ai-model "<model>"`** on every `reply` and `comment`. This is required — it marks your message as written by software and records your model name. Examples: `"Claude Opus 4.6"`, `"GPT-4o"`, `"Gemini 2.5 Pro"`.
- **Never respond to resolved threads** — they are closed.
- **Keep replies concise** — this is margin dialogue, not an essay.
- **Make minimal targeted edits** when changing the document.
- **Use the file reference** to read more context when the snippet isn't enough. The `doc.md:line:col` reference points to the exact anchored passage.
- **Parallelism**: for many independent threads, run multiple `scholia reply` calls in parallel with `-q`. Don't parallelize when one reply depends on a document edit from another, or when threads concern overlapping sections.
- The human sees replies live in the browser sidebar.

## Example Session

```
$ scholia list doc.md
[open] urn:uuid:a8c086ab-3949-4abe-9679-4e41e05827b8
  doc.md:13:8-28
  in § Consistency Model
  11 |  ## Consistency Model
  12 |
  13 |  We use eventual consistency with a maximum staleness window of 30 seconds.
     |         ^^^^^^^^^^^^^^^^^^^^
  14 |  Write-through caching ensures the database is always the source of truth,
  15 |  but read replicas may serve slightly stale data during the convergence window.

  [alice] Is 30 seconds too long? Users might see stale prices.

[open] urn:uuid:c4e21203-dafa-4530-a6c9-afecdb2f7b60
  doc.md:19:39-76
  in § Failure Modes
  17 |  ## Failure Modes
  18 |
  19 |  When Redis is unavailable, the system falls back to direct database queries.
     |                                        ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  20 |  This degradation is transparent to the caller but increases p99 latency
  21 |  from ~5ms to ~50ms.

  [alice] Should we add a circuit breaker here instead of unbounded fallback?

$ scholia reply doc.md a8c0 "Good catch. For pricing data we should tighten this to 5s. I'll update the config." --author-ai-model "Claude Opus 4.6"
Reply added to urn:uuid:a8c086ab-3949-4abe-9679-4e41e05827b8

$ scholia resolve doc.md a8c0
Resolved urn:uuid:a8c086ab-3949-4abe-9679-4e41e05827b8
```

## Configuration

- `SCHOLIA_USERNAME` env var sets the human display name in comments (falls back to system username).

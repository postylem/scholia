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

# Control context lines around anchored text (default: 2 before, 2 after)
scholia list <doc.md> --context 1 1
scholia list <doc.md> --context 0 0   # anchor line(s) only

# Show a single thread (accepts ID prefix — e.g. 'a8c0' instead of full urn:uuid:...)
# Also accepts --context N M to control surrounding lines
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

### Exporting

```bash
# Export to PDF (requires a LaTeX engine: xelatex, tectonic, etc.)
scholia export <doc.md>
scholia export <doc.md> --to pdf

# Export to standalone HTML or LaTeX source
scholia export <doc.md> --to html
scholia export <doc.md> --to latex

# Custom output path or LaTeX engine
scholia export <doc.md> -o output.pdf
scholia export <doc.md> --pdf-engine tectonic
```

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

6. **Follow-up reviews.** For iterative review sessions (when you've already reviewed this document before), use `scholia list <doc.md> --since <ISO-timestamp>` to see only threads with activity since your last pass. Note the current time before listing so you can use it as the `--since` value next time.

## Guidelines

- **Use short IDs default**: Always pass the short 4-8 character ID prefix (e.g. `a8c0`) instead of the full `urn:uuid:...` to save context tokens.
- **Always pass `--author-ai-model "<model>"`** on every `reply` and `comment`. This is required — it marks your message as written by software and records your model name. Examples: `"Claude Opus 4.6"`, `"GPT-4o"`, `"Gemini 2.5 Pro"`.
- **Never respond to resolved threads** — they are closed.
- **Keep replies concise** — this is margin dialogue, not an essay.
- **Make minimal targeted edits** when changing the document.
- **Use the file reference** to read more context when the snippet isn't enough. The `doc.md:line:col` reference points to the exact anchored passage.
- **Parallelism**: for many independent threads, run multiple `scholia reply` calls in parallel with `-q`. Don't parallelize when one reply depends on a document edit from another, or when threads concern overlapping sections.
- The human sees replies live in the browser sidebar.

## Cross-references (pandoc-crossref)

When writing or editing documents, use `pandoc-crossref` identifiers so that section numbers, figure numbers, etc. stay correct automatically — even when content is reordered.

### Naming convention

| Type     | Attribute on definition         | Reference syntax  | Renders as      |
|----------|---------------------------------|-------------------|-----------------|
| Section  | `## Methods {#sec:methods}`     | `@sec:methods`    | sec. 2          |
| Figure   | `![Caption](img.png){#fig:arch}`| `@fig:arch`       | fig. 1          |
| Table    | `: Caption {#tbl:results}`      | `@tbl:results`    | tbl. 1          |
| Equation | `$$ E=mc^2 $$ {#eq:energy}`     | `@eq:energy`      | eq. 1           |
| Listing  | `` {#lst:main} ``               | `@lst:main`       | lst. 1          |

### Rules

- Always use the `prefix:label` pattern (`sec:`, `fig:`, `tbl:`, `eq:`, `lst:`) — this is how `pandoc-crossref` dispatches reference types.
- Never hard-code section/figure numbers (e.g. `[§3](#methods)`). Use `@sec:methods` instead — numbers update automatically when sections are reordered.
- When creating new headings, always add an explicit id: `## New Section {#sec:new-section}`.
- When referencing multiple items: `@sec:intro; @sec:methods` renders as "secs. 1, 2".

## Example Session

```
$ scholia list doc.md
d599
  doc.md:7:8-28
  in § Consistency Model
  5 |  ## Consistency Model
  6 |
  7 |  We use eventual consistency with a maximum staleness window of 30 seconds.
    |         ^^^^^^^^^^^^^^^^^^^^
  8 |  Write-through caching ensures the database is always the source of truth,
  9 |  but read replicas may serve slightly stale data during the convergence window.

  [alice] Is 30 seconds too long? Users might see stale prices.

2f4f
  doc.md:13:39-76
  in § Failure Modes
  11 |  ## Failure Modes
  12 |
  13 |  When Redis is unavailable, the system falls back to direct database queries.
     |                                        ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  14 |  This degradation is transparent to the caller but increases p99 latency
  15 |  from ~5ms to ~50ms.

  [alice] Should we add a circuit breaker here instead of unbounded fallback?

$ scholia reply doc.md d599 "Good catch. For pricing data we should tighten this to 5s. I'll update the config." --author-ai-model "Claude Opus 4.6"
Reply added to urn:uuid:d5998950-b501-4cb8-a323-aae0409b1aa1

$ scholia resolve doc.md d599
Resolved urn:uuid:d5998950-b501-4cb8-a323-aae0409b1aa1
```

## Configuration

- `SCHOLIA_USERNAME` env var sets the human display name in comments (falls back to system username).

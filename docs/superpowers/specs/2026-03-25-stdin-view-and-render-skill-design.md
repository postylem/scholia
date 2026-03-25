# Stdin support for `scholia view` + agent render skill

**Date:** 2026-03-25
**Scope:** CLI enhancement + skill file update
**Future:** MCP integration deferred to v0.7 (pending MCP education session)

## Motivation

When an AI agent produces a response containing display math, diagrams, complex
tables, or long structured content, the terminal is a poor rendering surface.
Scholia already has a full rendering pipeline (Pandoc + KaTeX + syntax
highlighting + Tufte CSS) and a live-reload server. Two small additions make
this pipeline available as a general-purpose rendering surface for agent output:

1. Let `scholia view` accept markdown on stdin (for shell ergonomics).
2. Teach the agent *when* and *how* to render via a new section in the existing
   skill file.

Note: the agent does not use `scholia view -` itself. It writes a temp file
with the Write tool (giving it a stable path for subsequent edits and
annotation workflows), then runs `scholia view <path>`. Stdin support is for
human/shell ergonomics — piping from other commands, quick one-liners, etc.

## Part 1: `scholia view -` (stdin support)

### Interface

```bash
# Read markdown from stdin
echo '$$E=mc^2$$' | scholia view -

# With a title (becomes YAML frontmatter)
cat proof.md | scholia view - --title "Cauchy integral formula"

# Existing usage unchanged
scholia view doc.md
scholia view          # interactive picker
```

### Behavior

- When `doc` is `-`, read all of stdin as UTF-8 text and write to a temp file.
  Non-UTF-8 input produces an error: `"Error: stdin is not valid UTF-8 text"`.
- Empty stdin is allowed — creates an empty temp file (or title-only frontmatter
  if `--title` is given). The server starts and live-reloads when content is
  written later.
- Temp file path: use `tempfile.mkstemp(prefix="scholia-", suffix=".md")`.
  The actual path varies by OS (e.g. `/var/folders/.../T/` on macOS, `/tmp/` on
  Linux). Use `os.fdopen(fd, 'w')` to write content through the returned fd,
  then close it before passing the path to the server.
- Print `Viewing <path>` to stderr (not stdout, so piping works). The normal
  server startup message (`Scholia serving ... at http://...`) prints as usual.
- If `--title` is provided, prepend YAML frontmatter (`---\ntitle: <title>\n---\n\n`)
  before the stdin content.
- File watching is active on the temp file — any later writes to it trigger a
  live-reload in the browser, exactly like a normal `scholia view` session.
- The temp file is **not** auto-deleted. The user or agent may update or
  annotate it after initial creation. OS temp cleanup handles it eventually.

### Piped stdin without `-`

If stdin is a pipe but no `doc` argument is given (`echo '...' | scholia view`),
the interactive picker would try to read from the consumed stdin and fail.
Detect this case: if `doc` is `None` and `not sys.stdin.isatty()`, print a
helpful error: `"Error: stdin is not a terminal — did you mean 'scholia view -'?"`
and exit.

### `--title` flag

- Added to the `view` subparser alongside `--host` and `--port`.
- Meaningful with `-` (stdin) — prepends YAML frontmatter.
- Ignored with a warning to stderr if given with a file path or if the
  interactive picker runs: `"Warning: --title is only used with stdin mode (scholia view -)"`.

### Implementation notes

- The change is entirely in `cmd_view()` in `cli.py`. No server changes needed.
- Sequence: read stdin → write temp file → construct `ScholiaServer` with the
  temp file path. The server validates that the file exists at construction
  time, so the file must be written first.

## Part 2: Agent render skill (new section in existing skill file)

### Location

Add a new section to `scholia/data/agent-instructions.md`, titled
**"Using scholia to render agent responses"**. This keeps all scholia agent
guidance in one skill file.

### Trigger behavior

The skill description in the YAML frontmatter is updated to mention rendering
alongside annotation review, so the skill activates for both use cases.

### Section content (summary)

The new section teaches the agent:

**1. When to suggest rendering.** The agent should offer to render when its
response would contain:
- Display math (`$$...$$` or multi-line equations)
- Mermaid, TikZ, or other diagram markup
- More than ~3 code blocks
- Long proofs, derivations, or structured technical content
- Complex tables

The agent should NOT render for: short answers, single code snippets,
plain prose, or conversational replies.

**2. How to suggest.** Say something like:

> "This would be easier to read rendered in the browser — want me to open it
> with scholia?"

Wait for confirmation before proceeding.

**3. How to render.** Once the user agrees:
- Write the response to a temp markdown file with a descriptive slug
  (e.g. `/tmp/scholia-cauchy-proof.md`). The agent chooses the path and
  filename — it does not pipe through `scholia view -`, because it needs a
  stable path for subsequent edits and annotation workflows.
- Include YAML frontmatter with at least `title:`.
- Run `scholia view <path>` in the background.
- Tell the user the file path and that it's open in the browser.

**4. Updating.** If the user asks for changes, edit the same file. The browser
live-updates automatically via the file watcher.

**5. Annotation loop.** The user can add comments in the browser sidebar. If
they say "check the scholia" (or similar), the agent uses `scholia list <path>`
to read the annotations and responds — either by updating the file or replying
to threads. This follows the same review workflow described earlier in the skill
file.

### Example session

```
$ # Agent writes the file
$ cat /tmp/scholia-fourier-proof.md
---
title: Fourier Transform Proof
---

The Fourier transform of $f$ is defined as:

$$\hat{f}(\xi) = \int_{-\infty}^{\infty} f(x)\, e^{-2\pi i x \xi}\, dx$$

...

$ # Agent opens it in the background
$ scholia view /tmp/scholia-fourier-proof.md &
Scholia serving /tmp/scholia-fourier-proof.md at http://127.0.0.1:8088

$ # User comments in the browser, then asks agent to check
$ scholia list /tmp/scholia-fourier-proof.md
a1b2
  scholia-fourier-proof.md:7:1-60
  in § (untitled)
  ...
  [alice] Can you expand on why this integral converges?

$ scholia reply /tmp/scholia-fourier-proof.md a1b2 "Added a convergence note to the proof." --author-ai-model "Claude Opus 4.6"
```

### Skill metadata update

The YAML frontmatter `description` field is updated from:

> Review and respond to scholia annotations on markdown documents. Use when
> asked to check comments, review scholia, or respond to annotations.

To:

> Review and respond to scholia annotations on markdown documents, or render
> rich agent responses (math, diagrams, code) in the browser. Use when asked
> to check comments, review scholia, respond to annotations, or when a
> response would benefit from rendered display.

## Part 3: MCP integration (deferred)

MCP server integration is deferred to v0.7. Before planning that work, the
user needs an explanation of how MCP differs from the skill-based approach in
terms of robustness, efficiency, usefulness, and portability — this should
happen as a prerequisite conversation when v0.7 planning begins.

Placeholder tools to consider at that time:

| Tool | Purpose |
|------|---------|
| `render` | Accept markdown + optional title, manage temp file + server, return `{url, path}` |
| `update_render` | Update an existing rendered file by path |
| `list_annotations` | List open annotation threads (wraps `scholia list`) |
| `reply_annotation` | Reply to a specific thread |

## Testing

- **Stdin view:** Test that `echo '# Hello' | scholia view -` creates a temp
  file with the expected content and starts the server. Test `--title` prepends
  frontmatter. Test that `-` is only recognized as stdin (not a literal
  filename). Test empty stdin creates the file and starts the server. Tests
  should clean up temp files in teardown.
- **Piped-without-dash guard:** Test that piping to `scholia view` (no `-`)
  produces the helpful error message rather than falling into the interactive
  picker.
- **Skill file:** Existing `test_skill_init_template_is_agent_agnostic` test
  continues to pass. Add a test that the skill file contains both the review
  workflow section and the new rendering section.

## Non-goals

- No separate `scholia render` command — `scholia view -` and
  `scholia view <tmpfile>` cover the use case without a new subcommand.
- No auto-detection hook (Claude Code hook that pattern-matches output for
  math/diagrams). The skill's suggest-then-confirm flow is sufficient for now.
- No streaming from Claude's output to the file — Claude writes the complete
  file, then the browser renders it. Incremental updates happen via subsequent
  file edits.

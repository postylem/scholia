# PDF Export & WebSocket Connection Resilience

**Date:** 2026-03-25
**Status:** Draft
**Motivation:** Inspired by [markdown-live-preview](https://github.com/ComotionLabs/markdown-live-preview) — scholia's live preview is stronger on rendering features but lacked PDF export and connection resilience.

---

## Feature 1: Multi-format Pandoc Export

### Overview

Add a `scholia export` CLI subcommand that renders a markdown document to PDF, standalone HTML, or LaTeX via Pandoc. The PDF option is also exposed as a button in the browser UI's Options menu. On LaTeX engine failure, the browser gracefully degrades to `window.print()` with a prominent warning.

### CLI Interface

```
scholia export doc.md                  # defaults to pdf
scholia export doc.md --format pdf     # explicit
scholia export doc.md --format html    # standalone HTML5
scholia export doc.md --format latex   # LaTeX source
scholia export doc.md -o custom.pdf    # custom output path
```

- `--format` / `-f`: one of `pdf`, `html`, `latex`. Default: `pdf`.
- `--output` / `-o`: output file path. Default: `<input-stem>.<ext>` in the current directory, where `<ext>` is `pdf`, `html`, or `tex`.
- Prints the output path on success.

### Shared Pandoc Command Construction

Currently `_render_pandoc_sync()` in `server.py` builds a Pandoc command for HTML fragment output. The common options (katex, crossref, citeproc, bibliography/csl resolution, macros injection, number-sections, syntax highlighting) will be extracted into a shared helper:

```python
def _build_pandoc_base_cmd(doc_path: Path) -> tuple[list[str], str]:
    """Build common Pandoc args and return (cmd, processed_md_text).

    Handles: katex, crossref, citeproc, section-divs, syntax highlighting,
    bibliography/csl, macros injection, number-sections.
    """
```

This returns the base command list and the (possibly macro-injected) markdown text. Callers append format-specific flags:

- **HTML fragment** (existing `_render_pandoc_sync`): `--to=html5 --template=pandoc-fragment.html` + optional sidenote filter
- **Export PDF**: `--to=pdf --standalone`
- **Export HTML**: `--to=html5 --standalone --katex` (standalone page with KaTeX CDN links)
- **Export LaTeX**: `--to=latex --standalone`

### LaTeX Engine Detection & Graceful Degradation

For PDF output, Pandoc requires a LaTeX engine (`xelatex`, `lualatex`, `pdflatex`, or `tectonic`). Rather than checking at import time, we attempt the Pandoc command and catch failure:

- If Pandoc exits with an error mentioning the PDF engine, we detect it from stderr.
- **CLI behavior:** Print a clear error: `"PDF export requires a LaTeX engine (xelatex, tectonic, etc.). Install one, or use --format html/latex instead."`
- **Browser behavior:** The `/api/export-pdf` endpoint returns a JSON error. The frontend shows a warning banner: `"PDF export requires a LaTeX engine. Falling back to browser print."` Then calls `window.print()`.

The warning banner in the browser should be visually prominent (not easily missed) since browser print produces noticeably worse output.

### Server Endpoint

```
GET /api/export-pdf?file=<absolute-path>
```

- Runs the PDF export via `_render_export_sync()` in a thread executor.
- On success: returns PDF bytes with `Content-Type: application/pdf` and `Content-Disposition: attachment; filename="<stem>.pdf"`.
- On LaTeX failure: returns `{"error": "...", "fallback": "print"}` with status 422. Frontend handles the fallback.

### Browser UI

A single "Export PDF" item added to the **Options dropdown menu** (alongside Theme, Font, Zoom, Sidenotes). Not a standalone toolbar button — it's not commonly needed.

Clicking it:
1. Shows brief "Exporting..." feedback (e.g., button text changes)
2. Fetches `/api/export-pdf?file=...`
3. On success: triggers browser download of the PDF
4. On error with `fallback: "print"`: shows warning banner, then calls `window.print()`

### `server.py` Changes

- New function: `_build_pandoc_base_cmd(doc_path)` — extracted shared command construction
- New function: `_render_export_sync(doc_path, fmt, output_path)` — export to pdf/html/latex
- New async wrapper: `render_export(doc_path, fmt, output_path)`
- Refactor: `_render_pandoc_sync()` calls `_build_pandoc_base_cmd()` then appends HTML-specific flags
- New route: `/api/export-pdf` handler

### `cli.py` Changes

- New subcommand: `export` with `doc`, `--format`, `--output` args
- New function: `cmd_export(args)` — calls the shared export function

---

## Feature 2: WebSocket Connection Resilience

### Overview

Enhance the existing `connectWS()` function with exponential backoff and a visible disconnect banner. The current implementation reconnects with a fixed 2-second delay and has no visual indicator.

### Exponential Backoff

Replace the fixed `setTimeout(connectWS, 2000)` with:

```
attempt 1:  2s
attempt 2:  4s
attempt 3:  8s
attempt 4: 16s
attempt 5: 30s  (capped)
...
```

Formula: `min(2000 * 2^attempt, 30000)` milliseconds.

Reset attempt counter to 0 on successful `onopen`.

Add an `onerror` handler that logs to console (informational only — `onclose` fires after errors and handles the reconnection).

### Disconnect Banner

A narrow, fixed-position bar that appears below the toolbar when the WebSocket is disconnected.

**Behavior:**
- Appears on `onclose` (with a short delay, e.g., 500ms, to avoid flashing during normal reconnects)
- Disappears on `onopen` (immediate, with a fade-out)
- `pointer-events: none` — never blocks clicks on content underneath
- Text: "Reconnecting..." (optionally with a pulsing dot CSS animation)

**Positioning:**
- Fixed, below the toolbar (`top: <toolbar-height>px`)
- Full width, narrow height (~28px)
- Semi-transparent background matching theme (light/dark aware)
- Fades in/out with CSS transitions

**No message queuing:** If the user tries to interact while disconnected, `wsSend()` already silently drops (WS not OPEN). The banner makes this state visible. No other behavior change needed.

### `scholia.js` Changes

- Modify `connectWS()`: add attempt counter, compute backoff delay, reset on open
- Add `onerror` handler (console.warn)
- Add `showDisconnectBanner()` / `hideDisconnectBanner()` functions
- Call show/hide from `onclose`/`onopen`
- Add banner DOM element creation (once, on init)

### `scholia.css` Changes

- Style for `.scholia-disconnect-banner`: fixed position, transition, pointer-events, theme-aware colors

---

## Testing

### PDF Export

- Unit test: `_build_pandoc_base_cmd()` returns expected flags for docs with/without crossref, bibliography, number-sections, macros
- Unit test: `cmd_export()` with `--format html` and `--format latex` produce output files (no LaTeX engine needed)
- Integration test: `/api/export-pdf` endpoint returns PDF bytes (skip in CI if no LaTeX engine)
- Integration test: `/api/export-pdf` returns fallback error when LaTeX engine is missing

### Connection Resilience

- Unit test: backoff calculation produces expected delays (2, 4, 8, 16, 30, 30, ...)
- Manual test: kill and restart server, observe banner appears/disappears and backoff behavior

---

## Files Changed

| File | Change |
|------|--------|
| `scholia/server.py` | Extract `_build_pandoc_base_cmd()`, add export functions, add `/api/export-pdf` route |
| `scholia/cli.py` | Add `export` subcommand |
| `scholia/static/scholia.js` | Add PDF export button in Options menu, add WS backoff + disconnect banner |
| `scholia/static/scholia.css` | Disconnect banner styles, export-related styles |
| `tests/` | New tests for export and backoff |

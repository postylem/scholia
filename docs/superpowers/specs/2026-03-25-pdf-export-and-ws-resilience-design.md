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
scholia export doc.md --to pdf         # explicit
scholia export doc.md --to html        # standalone HTML5
scholia export doc.md --to latex       # LaTeX source
scholia export doc.md -o custom.pdf    # custom output path
scholia export doc.md --pdf-engine tectonic  # specific LaTeX engine
```

- `--to` / `-t`: one of `pdf`, `html`, `latex`. Default: `pdf`. (Named `--to` rather than `--format` to avoid ambiguity with the existing `--format` flag on `list`/`show`, and to mirror Pandoc's own `--to` convention.)
- `--output` / `-o`: output file path. Default: `<input-stem>.<ext>` in the current directory, where `<ext>` is `pdf`, `html`, or `tex`.
- `--pdf-engine`: optional passthrough to Pandoc's `--pdf-engine` flag (e.g. `xelatex`, `tectonic`, `lualatex`). Only relevant for `--to pdf`.
- Prints the output path on success.

### Shared Pandoc Command Construction

Currently `_render_pandoc_sync()` in `server.py` builds a Pandoc command for HTML fragment output. The **format-agnostic** options will be extracted into a shared helper:

```python
def _build_pandoc_base_cmd(doc_path: Path) -> tuple[list[str], str]:
    """Build format-agnostic Pandoc args and return (cmd, processed_md_text).

    Handles: crossref (if available), citeproc, bibliography/csl resolution,
    macros injection, number-sections, --metadata=link-citations:true,
    --from=markdown+tex_math_single_backslash.

    Does NOT include format-specific flags:
    - --katex (HTML-only; LaTeX/PDF handle math natively)
    - --section-divs (HTML-only; wraps sections in <section> tags)
    - --syntax-highlighting=pygments (valid for all formats but see note)
    - --template (format-specific)
    - --standalone (export-only)
    - --lua-filter sidenote.lua (HTML live-preview only)
    """
```

This returns the base command list and the (possibly macro-injected) markdown text. **Callers append format-specific flags:**

- **HTML fragment** (existing `_render_pandoc_sync`): `--katex --section-divs --syntax-highlighting=pygments --to=html5 --template=pandoc-fragment.html` + optional sidenote filter
- **Export PDF**: `--to=pdf --standalone --resource-path=<doc_dir>` + optional `--pdf-engine=<engine>`
- **Export HTML**: `--to=html5 --standalone --katex --section-divs --syntax-highlighting=pygments`
- **Export LaTeX**: `--to=latex --standalone`

**Note on `--syntax-highlighting`:** The `pygments` highlight style name is valid for LaTeX/PDF output too (Pandoc translates it to LaTeX color commands), so it is included in the export HTML caller and could optionally be added to PDF/LaTeX callers. However, the visual result will differ from the browser preview. For the initial implementation, PDF/LaTeX export will use Pandoc's default highlighting (which is reasonable) — this can be revisited.

**Note on sidenotes:** The sidenote Lua filter is only applied for the HTML live-preview path. Export does not apply it — footnotes remain as standard footnotes/endnotes in all export formats. The sidenote filter produces HTML-specific markup that would need a completely different approach for LaTeX (`\marginpar` etc.), which is out of scope.

**Note on `_render_markdown_fragment_sync`:** The separate function for rendering comment body fragments (server.py lines 137-158) is deliberately excluded from this refactoring. It has simpler needs (no section-divs, no template, no macros) and sharing the base command would add complexity without benefit.

### Resource Path Resolution

For export formats (especially PDF), Pandoc needs to resolve relative image paths. The existing code sets `cwd=str(doc_path.parent)` which helps for bibliography resolution. For export, we additionally pass `--resource-path=<doc_dir>` so Pandoc can locate images and other resources referenced with relative paths.

### LaTeX Engine Detection & Graceful Degradation

For PDF output, Pandoc requires a LaTeX engine (`xelatex`, `lualatex`, `pdflatex`, or `tectonic`). Rather than checking at import time, we attempt the Pandoc command and catch failure:

- If Pandoc exits with an error mentioning the PDF engine, we detect it from stderr.
- **CLI behavior:** Print a clear error: `"PDF export requires a LaTeX engine (xelatex, tectonic, etc.). Install one, or use --to html/latex instead."`
- **Browser behavior:** The `/api/export-pdf` endpoint returns a JSON error. The frontend shows a warning banner: `"PDF export requires a LaTeX engine. Falling back to browser print."` Then calls `window.print()`.

The warning banner in the browser should be visually prominent (not easily missed) since browser print produces noticeably worse output.

### Server Endpoint

```
GET /api/export-pdf?file=<absolute-path>
```

- Runs the PDF export via `render_export()` in a thread executor.
- On success: returns PDF bytes with `Content-Type: application/pdf` and `Content-Disposition: attachment; filename="<stem>.pdf"`.
- On LaTeX failure: returns `{"error": "...", "fallback": "print"}` with status 422. Frontend handles the fallback.

**Security note:** This endpoint accepts an absolute file path, consistent with the existing `/?file=` and `/api/list-dir?path=` routes. Scholia is designed as a local-only server (bound to 127.0.0.1 by default), so this follows the existing trust model.

**Function signature for dual use (CLI writes file, server returns bytes):**

```python
def _render_export_sync(doc_path: Path, fmt: str, output_path: Path | None = None) -> bytes | None:
    """Export document. If output_path is None, return bytes (for server). Otherwise write to file."""
```

For PDF: when `output_path` is None, use Pandoc's `-o -` (stdout) to capture bytes. When `output_path` is given, pass `-o <path>` to let Pandoc write directly.

### Browser UI

A single "Export PDF" item added to the **Options dropdown menu** (alongside Theme, Font, Zoom, Sidenotes). Not a standalone toolbar button — it's not commonly needed.

Clicking it:
1. Shows brief "Exporting..." feedback (e.g., button text changes)
2. Fetches `/api/export-pdf?file=...`
3. On success: triggers browser download of the PDF
4. On error with `fallback: "print"`: shows warning banner, then calls `window.print()`

### `server.py` Changes

- New function: `_build_pandoc_base_cmd(doc_path)` — extracted format-agnostic command construction
- New function: `_render_export_sync(doc_path, fmt, output_path)` — export to pdf/html/latex
- New async wrapper: `render_export(doc_path, fmt, output_path)`
- Refactor: `_render_pandoc_sync()` calls `_build_pandoc_base_cmd()` then appends HTML-specific flags
- New route: `/api/export-pdf` handler

### `cli.py` Changes

- New subcommand: `export` with `doc`, `--to`, `--output`, `--pdf-engine` args
- New function: `cmd_export(args)` — calls the shared export function

---

## Feature 2: WebSocket Connection Resilience

### Overview

Enhance the existing `connectWS()` function with exponential backoff and a visible disconnect banner. The current implementation reconnects with a fixed 2-second delay and has no visual indicator.

### Exponential Backoff

Replace the fixed `setTimeout(connectWS, 2000)` with:

```
reconnect 0:  2s   (2000 * 2^0)
reconnect 1:  4s   (2000 * 2^1)
reconnect 2:  8s   (2000 * 2^2)
reconnect 3: 16s   (2000 * 2^3)
reconnect 4: 30s   (capped)
...
```

Formula: `min(2000 * 2^n, 30000)` milliseconds, where `n` starts at 0 and increments on each reconnect attempt.

Reset `n` to 0 on successful `onopen`.

Add an `onerror` handler that logs to console (informational only — `onclose` fires after errors and handles the reconnection).

### Disconnect Banner

A narrow, fixed-position bar that appears below the toolbar when the WebSocket is disconnected.

**Behavior:**
- Appears on `onclose` after a **500ms delay** to avoid flashing during fast reconnects. **If `onopen` fires within that 500ms, the pending show is cancelled** — no flash.
- Disappears on `onopen` (immediate, with a fade-out transition)
- `pointer-events: none` — never blocks clicks on content underneath
- Text: "Reconnecting..." (with a pulsing dot CSS animation)

**Positioning:**
- Fixed, below the toolbar (`top: <toolbar-height>px`)
- Full width, narrow height (~28px)
- Semi-transparent background matching theme (light/dark aware)
- Fades in/out with CSS transitions

**No message queuing:** If the user tries to interact while disconnected, `wsSend()` already silently drops (WS not OPEN). The banner makes this state visible. No other behavior change needed.

### `scholia.js` Changes

- Modify `connectWS()`: add attempt counter `wsAttempt`, compute backoff delay, reset on open
- Add `onerror` handler (console.warn)
- Add `showDisconnectBanner()` / `hideDisconnectBanner()` functions with 500ms show-delay and cancellation
- Call show/hide from `onclose`/`onopen`
- Add banner DOM element creation (once, on init)

### `scholia.css` Changes

- Style for `.scholia-disconnect-banner`: fixed position, transition, pointer-events, theme-aware colors

---

## Testing

### PDF Export

- Unit test: `_build_pandoc_base_cmd()` returns expected flags for docs with/without crossref, bibliography, number-sections, macros
- Regression test: `_render_pandoc_sync()` produces identical HTML output after refactoring to use `_build_pandoc_base_cmd()` (run on a sample document with math, citations, and crossref)
- Unit test: `cmd_export()` with `--to html` and `--to latex` produce output files (no LaTeX engine needed)
- Integration test: `/api/export-pdf` endpoint returns PDF bytes (skip in CI if no LaTeX engine)
- Integration test: `/api/export-pdf` returns fallback error when LaTeX engine is missing

### Connection Resilience

- Unit test: backoff calculation produces expected delays (2000, 4000, 8000, 16000, 30000, 30000, ...)
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

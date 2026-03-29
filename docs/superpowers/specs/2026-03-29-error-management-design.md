# Error Management & Badge Harmonization

**Date:** 2026-03-29
**Status:** Approved

## Problem

Scholia handles render errors inconsistently:

- **`_broadcast()` has no error handling.** When pandoc/quarto fails during a live re-render, the exception propagates unhandled. The "Rendering..." banner stays visible forever, no error reaches the browser, and the terminal may show a raw Python traceback.
- **Initial load vs. live re-render differs.** Initial load shows a proper error page for pandoc failures but a 500 for quarto failures. Live re-renders silently fail.
- **Terminal output is inconsistent.** Sometimes pandoc stderr appears, sometimes it doesn't. Quarto errors are mixed with Python tracebacks.
- **Recovery is broken.** After a render error, fixing the source file doesn't reliably update the browser. Sometimes the page stays on "Rendering..." forever, sometimes it shows a stale 500.

Separately, the "Disconnected" and "Rendering..." badges have different sizing (font-size, padding, border-radius) and can appear simultaneously, which doesn't make sense.

## Design

### 1. Badge Harmonization

**CSS unification:** Both badges use the same base sizing — the rendering banner's current values are better:
- `font-size: 0.75rem`
- `padding: 0.15rem 0.5rem`
- `border-radius: 3px`

The disconnected badge keeps its amber toolbar override (strong visual signal for an offline state).

**Mutual exclusivity:** When the WebSocket disconnects, hide the rendering banner — you can't be rendering if you're disconnected. When it reconnects, hide the disconnected badge; the server will send `rendering_start` if a render is in progress.

### 2. Server-Side Error Handling

**In `_broadcast()`:** Wrap `render_doc()` in try/except catching `CalledProcessError` and `RuntimeError`:

- **On error:**
  1. Log to terminal: `[scholia] Render error ({display_path}): {subprocess stderr}` — no Python traceback.
  2. Send `{"type": "render_error", "message": "..."}` to all clients watching that document.
  3. Store the error: `self.render_errors[doc_path] = error_message`.
- **On success:**
  1. Clear `self.render_errors.pop(doc_path, None)`.
  2. Send `doc_update` as normal.

**On WebSocket `watch`:** After registering the client, if `self.render_errors[doc_path]` exists, immediately send the `render_error` message. This ensures reconnecting clients see the current error state.

**Warnings (exit 0 with stderr):** Log to terminal only: `[scholia] Render warning ({display_path}): {stderr}`. No browser notification.

**Initial page load:** No changes. The existing error page behavior in `_handle_index()` already works for first-load errors.

### 3. Frontend Error Banner

**New WebSocket message type: `render_error`**

When received:
1. Hide the "Rendering..." banner.
2. Show a persistent error overlay.

**Error overlay design:**
- Floating panel, fixed to top of viewport (stays visible as you scroll), overlaid on content (not pushing it down).
- Red/dark background, white text.
- Error message displayed in a monospace `<code>` block (these are terminal-style messages).
- Minimize/expand toggle button (`-`/`+` or `▾`/`▸`).
- **Expanded:** Full error message visible.
- **Collapsed:** Thin red strip with "Render error" label and expand button. Always visible, never auto-dismisses.

**Clearing:** When a `doc_update` message arrives (successful render), remove the error overlay entirely.

**Existing toast unchanged:** The current 5-second transient toast for `error` type messages (comment save failures, etc.) stays as-is. Only `render_error` gets the persistent overlay treatment.

### 4. State Transitions

```
File saved
  → watchdog detects change (200ms debounce)
  → _broadcast() sends "rendering_start" to all clients
  → Frontend shows "Rendering..." banner
  → render_doc() called
    → Success:
        clear self.render_errors[doc_path]
        send "doc_update"
        log warnings to terminal if stderr present
        Frontend: hide "Rendering...", remove error overlay, update content
    → Failure:
        store error in self.render_errors[doc_path]
        send "render_error" with message
        log error to terminal (no traceback)
        Frontend: hide "Rendering...", show error overlay

WebSocket disconnect:
  → Frontend: hide "Rendering...", show "Disconnected" badge + amber toolbar

WebSocket reconnect:
  → Frontend: hide "Disconnected" badge
  → Client sends "watch"
  → Server: if render_errors[doc_path] exists, send "render_error"
```

### 5. Test Fixtures

Create in `tests/fixtures/`:

| File | Content | Purpose |
|------|---------|---------|
| `error-yaml-bad.md` | Markdown with malformed YAML (`author: V:`) | Pandoc YAML parse error |
| `error-yaml-bad.qmd` | Same but `.qmd` | Quarto YAML parse error |
| `error-cell-exec.qmd` | Valid YAML, python cell with `1/0` | Quarto cell execution error |
| `error-none.md` | Valid markdown | Control case |
| `error-none.qmd` | Valid quarto | Control case |

### 6. Manual Testing Checklist

Walk through each scenario after implementation, for both `.md` and `.qmd` where applicable:

| # | Scenario | Terminal expected | Browser expected |
|---|----------|------------------|-----------------|
| 1 | Launch on file with error | `[scholia] Render error (file): ...` | Error page (initial load) |
| 2 | Fix the error, save | No error logged | Content renders, error clears |
| 3 | Launch on good file | No errors | Content renders normally |
| 4 | Introduce error, save | `[scholia] Render error (file): ...` | Error overlay appears, last-good content behind it |
| 5 | Introduce different error, save | New error logged | Overlay updates with new message |
| 6 | Fix the error, save | No error | Overlay disappears, content updates |
| 7 | Disconnect during rendering | — | "Disconnected" badge, no "Rendering..." |
| 8 | Reconnect after error state | — | Error overlay reappears |
| 9 | Good file with warnings on stderr | `[scholia] Render warning (file): ...` | No banner |

## Scope Boundaries

**In scope:** Everything above.

**Out of scope:**
- Changes to the initial page load error handling (already works).
- Changes to the render pipeline itself (pandoc/quarto invocation).
- The existing transient toast for non-render WebSocket errors.
- Automated (pytest) tests for the overlay UI — manual testing checklist covers this.

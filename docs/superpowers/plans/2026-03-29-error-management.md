# Error Management & Badge Harmonization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make render errors from pandoc/quarto surface consistently in both terminal and browser, with proper recovery when errors are fixed.

**Architecture:** Wrap `render_doc()` in `_broadcast()` with try/except, send a new `render_error` WebSocket message on failure, and handle it in the frontend with a persistent minimizable overlay. Also unify badge CSS and fix state priority between disconnected/rendering.

**Tech Stack:** Python (aiohttp server), vanilla JS frontend, CSS

---

### Task 1: Create test fixture files

**Files:**
- Create: `tests/fixtures/error-yaml-bad.md`
- Create: `tests/fixtures/error-yaml-bad.qmd`
- Create: `tests/fixtures/error-cell-exec.qmd`
- Create: `tests/fixtures/error-none.md`
- Create: `tests/fixtures/error-none.qmd`

These are manual testing fixtures, not pytest tests — they'll be used with `scholia view` to verify error handling.

- [ ] **Step 1: Create `error-yaml-bad.md`**

```markdown
---
title: Error Test
author: V:
---

This file has a YAML parse error (colon in unquoted value).
```

- [ ] **Step 2: Create `error-yaml-bad.qmd`**

```markdown
---
title: Error Test
author: V:
---

This file has a YAML parse error (colon in unquoted value).
```

- [ ] **Step 3: Create `error-cell-exec.qmd`**

```markdown
---
title: Cell Error Test
author: Test
---

Good content here.

```{python}
x = 1 / 0
```
```

- [ ] **Step 4: Create `error-none.md`**

```markdown
---
title: Good File
author: Test
---

This file renders without errors.

Some math: $x^2 + y^2 = z^2$
```

- [ ] **Step 5: Create `error-none.qmd`**

```markdown
---
title: Good File
author: Test
format:
  html:
    code-fold: false
---

This file renders without errors.

```{python}
print("hello")
```
```

- [ ] **Step 6: Commit**

```bash
git add tests/fixtures/error-yaml-bad.md tests/fixtures/error-yaml-bad.qmd tests/fixtures/error-cell-exec.qmd tests/fixtures/error-none.md tests/fixtures/error-none.qmd
git commit -m "test: add error scenario fixtures for manual testing"
```

---

### Task 2: Harmonize badge CSS

**Files:**
- Modify: `scholia/static/scholia.css:1881-1950`

The disconnect banner uses `font-size: 0.65rem`, `padding: 0.1rem 0.6rem`, `border-radius: var(--s-radius)`. The rendering banner uses `font-size: 0.75rem`, `padding: 0.15rem 0.5rem`, `border-radius: 3px`. Unify the disconnect banner to match rendering banner sizing, keeping its amber toolbar override.

- [ ] **Step 1: Update disconnect banner CSS to match rendering banner sizing**

In `scholia/static/scholia.css`, change `.scholia-disconnect-banner`:

```css
/* Before */
.scholia-disconnect-banner {
  display: none;
  align-items: center;
  color: white;
  font-size: 0.65rem;
  font-family: var(--s-sans);
  padding: 0.1rem 0.6rem;
  border-radius: var(--s-radius);
  white-space: nowrap;
  background: rgba(0, 0, 0, 0.15);
}

/* After */
.scholia-disconnect-banner {
  display: none;
  align-items: center;
  color: rgba(255, 255, 255, 0.85);
  font-size: 0.75rem;
  font-family: var(--s-sans);
  padding: 0.15rem 0.5rem;
  border-radius: 3px;
  white-space: nowrap;
  background: rgba(0, 0, 0, 0.15);
}
```

Changes: `font-size` 0.65→0.75rem, `padding` 0.1/0.6→0.15/0.5rem, `border-radius` var→3px, `color` white→rgba(255,255,255,0.85) to match rendering banner.

- [ ] **Step 2: Verify visually**

Run `scholia view tests/fixtures/error-none.md`, disconnect network or kill server briefly, confirm badge size matches the rendering banner.

- [ ] **Step 3: Commit**

```bash
git add scholia/static/scholia.css
git commit -m "fix: harmonize disconnect and rendering badge sizing"
```

---

### Task 3: Add render error overlay CSS

**Files:**
- Modify: `scholia/static/scholia.css` (add after rendering banner block, ~line 1950)

- [ ] **Step 1: Add error overlay CSS**

Insert after the `.scholia-rendering-banner.visible` animation block (after line 1950):

```css
/* Render-error overlay — persistent, minimizable */
.scholia-render-error {
  display: none;
  position: fixed;
  top: 48px;
  left: 50%;
  transform: translateX(-50%);
  max-width: 700px;
  width: 90%;
  z-index: 9999;
  font-family: var(--s-sans);
  border-radius: 6px;
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.3);
  overflow: hidden;
}
.scholia-render-error.visible {
  display: block;
}

/* Header bar — always visible, even when collapsed */
.scholia-render-error-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0.4rem 0.75rem;
  background: #c0392b;
  color: #fff;
  font-size: 0.8rem;
  font-weight: 600;
  cursor: pointer;
  user-select: none;
}
.scholia-render-error-header:hover {
  background: #a93226;
}

/* Toggle indicator */
.scholia-render-error-toggle {
  font-size: 0.7rem;
  opacity: 0.8;
  margin-left: 0.5rem;
}

/* Body — collapsible, contains the error message */
.scholia-render-error-body {
  padding: 0.6rem 0.75rem;
  background: #1a1a1a;
  color: #f0f0f0;
  font-family: ui-monospace, 'SF Mono', 'Cascadia Code', monospace;
  font-size: 0.75rem;
  line-height: 1.5;
  max-height: 200px;
  overflow-y: auto;
  white-space: pre-wrap;
  word-break: break-word;
}

/* Collapsed state: hide body */
.scholia-render-error.collapsed .scholia-render-error-body {
  display: none;
}
```

- [ ] **Step 2: Commit**

```bash
git add scholia/static/scholia.css
git commit -m "feat: add render error overlay CSS"
```

---

### Task 4: Server — error handling in `_broadcast()`

**Files:**
- Modify: `scholia/server.py:653-682` (add `render_errors` dict to `__init__`)
- Modify: `scholia/server.py:1076-1131` (`_broadcast` method)

- [ ] **Step 1: Add `render_errors` dict to `ScholiaServer.__init__`**

In `scholia/server.py`, add after `self._open_browser = open_browser` (line 681):

```python
        self.render_errors: dict[Path, str] = {}  # doc_path -> last error message
```

- [ ] **Step 2: Wrap render_doc() call in _broadcast() with error handling**

Replace the rendering section of `_broadcast()` (the `else` branch starting at line 1090). The full replacement for lines 1090–1126:

```python
        else:
            default_sidenotes = _has_footnotes(doc_path.read_text(encoding="utf-8"))
            by_sidenotes: dict[bool, list] = {}
            for ws in clients:
                sn = self.ws_sidenotes.get(ws, default_sidenotes)
                by_sidenotes.setdefault(sn, []).append(ws)

            closed = set()
            # Notify clients that rendering has started (for progress indicator)
            start_payload = json.dumps({"type": "rendering_start"})
            for ws in clients:
                try:
                    await ws.send_str(start_payload)
                except Exception:
                    closed.add(ws)

            try:
                for sn_val, ws_list in by_sidenotes.items():
                    rendered = await render_doc(doc_path, sidenotes=sn_val)
                    if _is_quarto(doc_path):
                        main_match = re.search(
                            r"<main[^>]*>(.*)</main>", rendered, re.DOTALL | re.IGNORECASE
                        )
                        html = main_match.group(1) if main_match else rendered
                    else:
                        html = rendered

                    # Log warnings (stderr on success) to terminal only
                    # (render_doc doesn't currently expose stderr on success,
                    #  so this is a placeholder for when it does — see note below)

                    payload = json.dumps(
                        {
                            "type": "doc_update",
                            "html": html,
                            "sidenotes": sn_val,
                        }
                    )
                    for ws in ws_list:
                        try:
                            await ws.send_str(payload)
                        except Exception:
                            closed.add(ws)

                # Render succeeded — clear any stored error
                self.render_errors.pop(doc_path, None)

            except (subprocess.CalledProcessError, RuntimeError) as exc:
                # Extract the useful error message
                if isinstance(exc, subprocess.CalledProcessError):
                    err_msg = (exc.stderr or str(exc)).strip()
                else:
                    err_msg = str(exc).strip()

                display = self._display_path(doc_path)
                print(f"[scholia] Render error ({display}): {err_msg}", file=sys.stderr)

                # Store and send to all clients
                self.render_errors[doc_path] = err_msg
                error_payload = json.dumps({"type": "render_error", "message": err_msg})
                for ws in clients:
                    try:
                        await ws.send_str(error_payload)
                    except Exception:
                        closed.add(ws)
```

**Note on warnings:** The current `_render_pandoc_sync` and `_render_quarto_sync` functions don't return stderr on success — pandoc uses `check=True` (which raises on failure, discards stderr on success) and quarto only captures stderr for the error case. To surface warnings, we'd need to change these functions to return stderr alongside the HTML. This is a small follow-up: change `_render_pandoc_sync` to use `check=False` and inspect `returncode` manually, then return `(stdout, stderr)`. For now, the plan handles errors correctly; warnings are logged when the render functions are updated to expose them.

- [ ] **Step 3: Verify the import — `sys` is already imported**

Check that `import sys` exists at the top of `server.py`. It should (it's used for `sys.stderr` elsewhere). If not, add it.

- [ ] **Step 4: Commit**

```bash
git add scholia/server.py
git commit -m "feat: catch render errors in _broadcast, log to terminal, send to clients"
```

---

### Task 5: Server — send stored error on reconnect

**Files:**
- Modify: `scholia/server.py:966-978` (the `watch` handler in `_handle_ws_message`)

- [ ] **Step 1: Send stored error after watch registration**

In `_handle_ws_message`, after the `watch` handler registers the client and starts watching (lines 970-978), add the error check before the `return`:

```python
            if msg_type == "watch":
                file_path = Path(msg["file"]).resolve()
                self.ws_file[ws] = file_path
                if file_path not in self.ws_clients:
                    self.ws_clients[file_path] = set()
                self.ws_clients[file_path].add(ws)
                if self._loop:
                    self._start_watching(file_path)
                # Send stored render error if one exists for this document
                stored_error = self.render_errors.get(file_path)
                if stored_error:
                    await ws.send_json({"type": "render_error", "message": stored_error})
                return
```

- [ ] **Step 2: Commit**

```bash
git add scholia/server.py
git commit -m "feat: send stored render error to reconnecting clients"
```

---

### Task 6: Server — catch RuntimeError on initial page load

**Files:**
- Modify: `scholia/server.py:788-802` (the except block in `_handle_index`)

Currently `_handle_index` catches `subprocess.CalledProcessError` but not `RuntimeError`. Quarto failures raise `RuntimeError` (line 215: `raise RuntimeError(f"quarto render failed: {result.stderr}")`), so initial page load for quarto with errors gives a 500.

- [ ] **Step 1: Add RuntimeError to the except clause**

Change line 788 from:

```python
        except subprocess.CalledProcessError as e:
```

to:

```python
        except (subprocess.CalledProcessError, RuntimeError) as e:
```

And update the error message extraction to handle both types — `CalledProcessError` has `.stderr`, `RuntimeError` only has `str(e)`:

```python
        except (subprocess.CalledProcessError, RuntimeError) as e:
            import html as html_mod

            if isinstance(e, subprocess.CalledProcessError):
                detail = e.stderr or str(e)
            else:
                detail = str(e)
            error_html = (
                "<h2>Render error</h2>"
                f"<p><code>{html_mod.escape(detail)}</code></p>"
            )
            page = _fill_template(
                self.template,
                title="Error — Scholia",
                html=error_html,
                doc_path=doc_path,
                display_path=display,
                readonly=True,
            )
```

Also log to terminal here for consistency:

```python
            display_for_log = self._display_path(doc_path)
            print(f"[scholia] Render error ({display_for_log}): {detail.strip()}", file=sys.stderr)
```

- [ ] **Step 2: Commit**

```bash
git add scholia/server.py
git commit -m "fix: catch RuntimeError (quarto) on initial page load"
```

---

### Task 7: Server — log warnings to terminal

**Files:**
- Modify: `scholia/server.py:110-131` (`_render_pandoc_sync`)
- Modify: `scholia/server.py:206-215` (`_render_quarto_sync`)
- Modify: `scholia/server.py:226-237` (`render_doc`)
- Modify: `scholia/server.py:1076-1131` (`_broadcast` — add warning logging)

The render functions currently discard stderr on success. Change them to return it alongside the HTML so `_broadcast` can log warnings.

- [ ] **Step 1: Change `_render_pandoc_sync` to return stderr on success**

```python
def _render_pandoc_sync(doc_path: Path, sidenotes: bool = False) -> tuple[str, str]:
    """Render markdown to HTML fragment using Pandoc (blocking).

    Returns (html, stderr) — stderr may contain warnings even on success.
    """
    cmd, md_text = _build_pandoc_base_cmd(doc_path)
    cmd += [
        "--katex",
        "--section-divs",
        "--syntax-highlighting=pygments",
        "--to=html5",
        "--template=" + _FRAGMENT_TEMPLATE,
    ]
    if sidenotes:
        cmd.extend(["--lua-filter", _SIDENOTE_FILTER])

    result = subprocess.run(
        cmd,
        input=md_text,
        capture_output=True,
        text=True,
        cwd=str(doc_path.parent),
    )
    if result.returncode != 0:
        raise subprocess.CalledProcessError(
            result.returncode, cmd, result.stdout, result.stderr
        )
    return result.stdout, result.stderr
```

Key change: removed `check=True`, manually check returncode, return `(stdout, stderr)`.

- [ ] **Step 2: Change `_render_quarto_sync` to return stderr on success**

```python
def _render_quarto_sync(doc_path: Path, use_defaults: bool = True) -> tuple[str, str]:
    """Render a Quarto document and return the full HTML page (blocking).

    Returns (html, stderr) — stderr may contain warnings even on success.
    """
    # ... (existing command building code unchanged until result check) ...

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        env=env,
        cwd=str(doc_path.parent),
        timeout=120,
    )
    if result.returncode != 0:
        raise RuntimeError(f"quarto render failed: {result.stderr}")

    html = out_file.read_text(encoding="utf-8")
    stem = doc_path.stem
    html = html.replace(f"{stem}_files/", "/quarto-assets/")
    return html, result.stderr
```

- [ ] **Step 3: Update `render_doc` to pass through the tuple**

```python
async def render_doc(
    doc_path: Path, sidenotes: bool = False, quarto_use_defaults: bool = True
) -> tuple[str, str]:
    """Render a document to HTML, choosing the right pipeline.

    Returns (html, stderr).
    For Quarto documents html is a complete HTML page.
    For Pandoc documents html is an HTML fragment.
    """
    loop = asyncio.get_running_loop()
    if _is_quarto(doc_path):
        return await loop.run_in_executor(None, _render_quarto_sync, doc_path, quarto_use_defaults)
    return await loop.run_in_executor(None, _render_pandoc_sync, doc_path, sidenotes)
```

- [ ] **Step 4: Update `render_pandoc` wrapper too**

```python
async def render_pandoc(doc_path: Path, sidenotes: bool = False) -> tuple[str, str]:
    """Render markdown to HTML fragment without blocking the event loop."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _render_pandoc_sync, doc_path, sidenotes)
```

- [ ] **Step 5: Update all callers of `render_doc`**

There are exactly two callers of `render_doc` in `server.py`:

1. `_broadcast()` at line 1106 (already updated in Task 4 — adjust to unpack):

In the `_broadcast` try block, change:
```python
                    rendered = await render_doc(doc_path, sidenotes=sn_val)
```
to:
```python
                    rendered, stderr = await render_doc(doc_path, sidenotes=sn_val)
                    if stderr.strip():
                        warn_display = self._display_path(doc_path)
                        print(f"[scholia] Render warning ({warn_display}): {stderr.strip()}", file=sys.stderr)
```

2. `build_page()` at line 529 — update to unpack:
```python
    html, _stderr = await render_doc(doc_path, sidenotes=sidenotes, quarto_use_defaults=use_defaults)
```
(Warnings during initial page load are less important — the user is about to see the page. Discard stderr here.)

No other callers exist. `render_markdown_fragment` and `_render_export_sync` are separate functions, unchanged.

- [ ] **Step 6: Run existing tests**

```bash
uv run pytest -v
```

Expected: all pass. The return type change may break tests that assert on the return value of `render_doc`.

- [ ] **Step 7: Commit**

```bash
git add scholia/server.py
git commit -m "feat: surface render warnings — return stderr from render functions"
```

---

### Task 8: Frontend — render_error handler and error overlay

**Files:**
- Modify: `scholia/static/scholia.js:381-418` (add error overlay element creation)
- Modify: `scholia/static/scholia.js:432-494` (add `render_error` handler in `onmessage`)

- [ ] **Step 1: Create the error overlay element**

In `scholia.js`, after the rendering banner setup (after line 418), add:

```javascript
  // ── Render error overlay (persistent, minimizable) ──
  var renderErrorOverlay = document.createElement('div');
  renderErrorOverlay.className = 'scholia-render-error';
  renderErrorOverlay.innerHTML =
    '<div class="scholia-render-error-header">' +
      '<span>Render error</span>' +
      '<span class="scholia-render-error-toggle">\u25BE</span>' +
    '</div>' +
    '<div class="scholia-render-error-body"></div>';
  var renderErrorCollapsed = false;

  renderErrorOverlay.querySelector('.scholia-render-error-header').addEventListener('click', function () {
    renderErrorCollapsed = !renderErrorCollapsed;
    renderErrorOverlay.classList.toggle('collapsed', renderErrorCollapsed);
    renderErrorOverlay.querySelector('.scholia-render-error-toggle').textContent =
      renderErrorCollapsed ? '\u25B8' : '\u25BE';
  });

  function showRenderError(message) {
    renderErrorOverlay.querySelector('.scholia-render-error-body').textContent = message;
    renderErrorOverlay.classList.remove('collapsed');
    renderErrorOverlay.querySelector('.scholia-render-error-toggle').textContent = '\u25BE';
    renderErrorCollapsed = false;
    renderErrorOverlay.classList.add('visible');
    hideRenderingBanner();
  }

  function hideRenderError() {
    renderErrorOverlay.classList.remove('visible');
  }
```

- [ ] **Step 2: Append the overlay to the shadow DOM**

Find where `disconnectBanner` and `renderingBanner` are appended (around line 783). Add after them:

```javascript
  shadow.appendChild(renderErrorOverlay);
```

Note: this goes on `shadow` (the shadow root), not `toolbarEl`, because it's a viewport-fixed overlay, not a toolbar inline element.

- [ ] **Step 3: Add `render_error` message handler**

In the `ws.onmessage` handler, add a new case after the `rendering_start` check (after line 437):

```javascript
      if (msg.type === 'render_error') {
        showRenderError(msg.message);
        return;
      }
```

- [ ] **Step 4: Clear error overlay on successful doc_update**

In the `doc_update` handler, add `hideRenderError()` call. For the non-Quarto path, add it right before `hideRenderingBanner()` (line 446):

```javascript
        hideRenderError();
        hideRenderingBanner();
```

For the Quarto path (which reloads the page), the overlay will naturally disappear on reload. But to be safe, add it before the reload too:

```javascript
        if (isQuarto) {
          hideRenderError();
          window.location.reload();
          return;
        }
```

- [ ] **Step 5: Commit**

```bash
git add scholia/static/scholia.js
git commit -m "feat: render error overlay — persistent, minimizable, clears on success"
```

---

### Task 9: Frontend — disconnect hides rendering banner (mutual exclusivity)

**Files:**
- Modify: `scholia/static/scholia.js:501-506` (`ws.onclose` handler)

- [ ] **Step 1: Hide rendering banner on disconnect**

In `ws.onclose`, add `hideRenderingBanner()` before `showDisconnectBanner()`:

```javascript
    ws.onclose = function () {
      hideRenderingBanner();
      showDisconnectBanner();
      var delay = Math.min(2000 * Math.pow(2, wsAttempt), 30000);
      wsAttempt++;
      setTimeout(connectWS, delay);
    };
```

- [ ] **Step 2: Commit**

```bash
git add scholia/static/scholia.js
git commit -m "fix: hide rendering banner on disconnect (mutual exclusivity)"
```

---

### Task 10: Manual testing walkthrough

Run through the testing checklist from the spec with the user. This task is interactive — the implementer runs `scholia view` and checks terminal output, the user checks browser behavior.

- [ ] **Step 1: Test .md with initial error**

```bash
scholia view tests/fixtures/error-yaml-bad.md
```

Terminal expected: `[scholia] Render error (tests/fixtures/error-yaml-bad.md): ...YAML parse error...`
Browser expected: Error page with the pandoc error message.

- [ ] **Step 2: Fix the error (edit the file to valid YAML), save**

Terminal expected: no error logged.
Browser expected: content renders, error clears.

- [ ] **Step 3: Test .md with no errors**

```bash
scholia view tests/fixtures/error-none.md
```

Terminal expected: no errors.
Browser expected: content renders normally.

- [ ] **Step 4: Introduce an error (edit to bad YAML), save**

Terminal expected: `[scholia] Render error (...): ...`
Browser expected: error overlay appears over last-good content.

- [ ] **Step 5: Introduce a different error, save**

Terminal expected: new error logged.
Browser expected: overlay updates with new error message.

- [ ] **Step 6: Fix the error, save**

Terminal expected: no error.
Browser expected: overlay disappears, content updates.

- [ ] **Step 7: Test .qmd with initial error**

```bash
scholia view tests/fixtures/error-yaml-bad.qmd
```

Terminal expected: `[scholia] Render error (...): ...`
Browser expected: error page (initial load).

- [ ] **Step 8: Test .qmd cell execution error**

```bash
scholia view tests/fixtures/error-cell-exec.qmd
```

Terminal expected: `[scholia] Render error (...): ...ZeroDivisionError...`
Browser expected: error page (initial load).

- [ ] **Step 9: Test good .qmd, then introduce error**

```bash
scholia view tests/fixtures/error-none.qmd
```

Then edit to introduce a bad cell. Terminal: error logged. Browser: error overlay.

- [ ] **Step 10: Test disconnect during rendering**

Open a .qmd file (slow render). While "Rendering..." is showing, kill the server.
Browser expected: "Disconnected" badge, no "Rendering..." badge.

- [ ] **Step 11: Test reconnect after error state**

Start server with a file that has an error. Fix the error. Disconnect. Reconnect.
Browser expected: if error is still stored, overlay shows on reconnect.

- [ ] **Step 12: Test warnings (if render functions updated)**

Find a file that produces pandoc warnings on stderr (e.g., missing citation key).
Terminal expected: `[scholia] Render warning (...): ...`
Browser expected: no banner.

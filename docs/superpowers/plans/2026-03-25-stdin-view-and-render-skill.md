# Stdin view + render skill Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let `scholia view -` read markdown from stdin, and teach AI agents when/how to render rich responses in the browser.

**Architecture:** Extract stdin-to-tempfile logic as a testable helper in `cli.py`. Add piped-stdin guard before the interactive picker. Append a new section to the existing agent instructions file.

**Tech Stack:** Python stdlib (`tempfile`, `os`, `sys`), existing test patterns (`subprocess.run`, `pytest tmp_path`)

**Spec:** `docs/superpowers/specs/2026-03-25-stdin-view-and-render-skill-design.md`

**Note:** Line numbers in task headers (e.g. `cli.py:277-285`) refer to the original unmodified file. They will shift as earlier tasks add lines.

---

### Task 1: Piped-stdin-without-dash guard

**Files:**
- Modify: `scholia/cli.py:277-285` (`cmd_view`)
- Create: `tests/test_view_stdin.py`

- [ ] **Step 1: Write the failing test**

```python
"""Tests for scholia view stdin support."""
import subprocess
import sys


def test_piped_stdin_without_dash_shows_error():
    """Piping to 'scholia view' without '-' gives helpful error."""
    result = subprocess.run(
        [sys.executable, "-m", "scholia.cli", "view"],
        input="# Hello",
        capture_output=True, text=True,
    )
    assert result.returncode != 0
    assert "did you mean" in result.stderr.lower()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_view_stdin.py::test_piped_stdin_without_dash_shows_error -v`
Expected: FAIL (currently falls into interactive picker or hangs)

- [ ] **Step 3: Implement the guard in `cmd_view`**

In `cli.py`, replace the current `cmd_view`:

```python
def cmd_view(args):
    from scholia.server import ScholiaServer

    if args.doc is None and not sys.stdin.isatty():
        print(
            "Error: stdin is not a terminal — did you mean 'scholia view -'?",
            file=sys.stderr,
        )
        sys.exit(1)

    doc = args.doc or _pick_or_create_doc()
    server = ScholiaServer(doc, host=args.host, port=args.port)
    try:
        asyncio.run(server.start())
    except (KeyboardInterrupt, SystemExit):
        pass
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_view_stdin.py::test_piped_stdin_without_dash_shows_error -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add scholia/cli.py tests/test_view_stdin.py
git commit -m "Guard against piped stdin without '-' in scholia view"
```

---

### Task 2: Basic stdin support (`scholia view -`)

**Files:**
- Modify: `scholia/cli.py:277-285` (`cmd_view`)
- Test: `tests/test_view_stdin.py`

The helper `_stdin_to_tempfile` is extracted so tests can verify temp-file creation without starting a server.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_view_stdin.py`:

```python
import os
import tempfile


def test_stdin_to_tempfile_creates_file():
    """_stdin_to_tempfile writes stdin content to a temp .md file."""
    from scholia.cli import _stdin_to_tempfile

    path = _stdin_to_tempfile("# Hello world\n")
    try:
        assert os.path.exists(path)
        assert path.endswith(".md")
        assert "scholia-" in os.path.basename(path)
        content = open(path).read()
        assert content == "# Hello world\n"
    finally:
        os.unlink(path)


def test_stdin_to_tempfile_non_utf8_errors():
    """_stdin_to_tempfile raises ValueError on non-UTF-8 input."""
    from scholia.cli import _stdin_to_tempfile
    import pytest

    with pytest.raises(ValueError, match="not valid UTF-8"):
        _stdin_to_tempfile(b"\x80\x81\x82")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_view_stdin.py::test_stdin_to_tempfile_creates_file tests/test_view_stdin.py::test_stdin_to_tempfile_non_utf8_errors -v`
Expected: FAIL (function doesn't exist)

- [ ] **Step 3: Implement `_stdin_to_tempfile` and wire it into `cmd_view`**

Add the helper to `cli.py` above `cmd_view`:

```python
def _stdin_to_tempfile(content, title=None):
    """Write content to a temp markdown file. Return the path.

    Args:
        content: str (decoded text) or bytes (validated as UTF-8).
        title: optional title string for YAML frontmatter.

    Returns:
        Path string to the temp file.

    Raises:
        ValueError: if content is bytes and not valid UTF-8.
    """
    if isinstance(content, bytes):
        try:
            content = content.decode("utf-8")
        except UnicodeDecodeError:
            raise ValueError("stdin is not valid UTF-8 text")

    if title:
        content = f"---\ntitle: {title}\n---\n\n{content}"

    fd, path = tempfile.mkstemp(prefix="scholia-", suffix=".md")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(content)
    return path
```

Add `import os, tempfile` to the imports at the top of `cli.py` (alongside `import argparse, asyncio, json, sys`).

Add `--title` to the `view` subparser (after the `--port` argument):

```python
    p_view.add_argument(
        "--title", default=None,
        help="Document title (YAML frontmatter, only used with stdin '-')",
    )
```

Update `cmd_view` to handle `-`:

```python
def cmd_view(args):
    from scholia.server import ScholiaServer

    if args.doc == "-":
        try:
            text = sys.stdin.read()
        except UnicodeDecodeError:
            print("Error: stdin is not valid UTF-8 text", file=sys.stderr)
            sys.exit(1)
        doc = _stdin_to_tempfile(text, title=args.title)
        print(f"Viewing {doc}", file=sys.stderr)
    elif args.doc is None and not sys.stdin.isatty():
        print(
            "Error: stdin is not a terminal — did you mean 'scholia view -'?",
            file=sys.stderr,
        )
        sys.exit(1)
    else:
        if args.title:
            print(
                "Warning: --title is only used with stdin mode (scholia view -)",
                file=sys.stderr,
            )
        doc = args.doc or _pick_or_create_doc()

    server = ScholiaServer(doc, host=args.host, port=args.port)
    try:
        asyncio.run(server.start())
    except (KeyboardInterrupt, SystemExit):
        pass
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_view_stdin.py -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add scholia/cli.py tests/test_view_stdin.py
git commit -m "Add stdin support to scholia view (scholia view -)"
```

---

### Task 3: `--title` and edge-case tests

**Files:**
- Test: `tests/test_view_stdin.py`

The `--title` argparse flag and `_stdin_to_tempfile` title handling were added in Task 2. This task adds tests to validate title, empty-stdin, and `--title`-with-file-warning behavior.

- [ ] **Step 1: Write the tests**

Add to `tests/test_view_stdin.py`:

```python
def test_stdin_to_tempfile_with_title():
    """_stdin_to_tempfile prepends YAML frontmatter when title given."""
    from scholia.cli import _stdin_to_tempfile

    path = _stdin_to_tempfile("Body text\n", title="My Title")
    try:
        content = open(path).read()
        assert content.startswith("---\ntitle: My Title\n---\n\n")
        assert content.endswith("Body text\n")
    finally:
        os.unlink(path)


def test_stdin_to_tempfile_empty_content():
    """Empty stdin creates a file (possibly with just frontmatter)."""
    from scholia.cli import _stdin_to_tempfile

    path = _stdin_to_tempfile("", title="Empty")
    try:
        content = open(path).read()
        assert "title: Empty" in content
        assert os.path.exists(path)
    finally:
        os.unlink(path)


def test_stdin_to_tempfile_empty_no_title():
    """Empty stdin with no title creates an empty file."""
    from scholia.cli import _stdin_to_tempfile

    path = _stdin_to_tempfile("")
    try:
        assert os.path.exists(path)
        assert open(path).read() == ""
    finally:
        os.unlink(path)


def test_title_flag_with_file_shows_warning(tmp_path):
    """--title with a file path prints a warning to stderr."""
    doc = tmp_path / "test.md"
    doc.write_text("# Hello")
    # Start the server; it won't exit on its own, so use a short timeout.
    # subprocess.run raises TimeoutExpired — check stderr on the exception.
    try:
        subprocess.run(
            [sys.executable, "-m", "scholia.cli", "view", str(doc), "--title", "Foo"],
            capture_output=True, text=True,
            timeout=3,
        )
    except subprocess.TimeoutExpired as e:
        assert e.stderr is not None
        assert "warning" in e.stderr.decode().lower()
```

- [ ] **Step 2: Run all stdin tests**

Run: `uv run pytest tests/test_view_stdin.py -v`
Expected: all PASS

- [ ] **Step 3: Commit**

```bash
git add tests/test_view_stdin.py
git commit -m "Add tests for --title flag, empty stdin, and title-with-file warning"
```

---

### Task 4: Agent render skill section

**Files:**
- Modify: `scholia/data/agent-instructions.md`
- Modify: `tests/test_init.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_init.py`:

```python
def test_skill_template_has_render_section():
    """Skill file includes section on rendering agent responses."""
    from scholia.cli import _load_instruction_template

    content = _load_instruction_template()
    assert "Using scholia to render agent responses" in content
    # Both workflows should be present
    assert "Review Workflow" in content
    assert "scholia view" in content
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_init.py::test_skill_template_has_render_section -v`
Expected: FAIL (section doesn't exist yet)

- [ ] **Step 3: Update YAML frontmatter in `agent-instructions.md`**

Change the frontmatter `description` from:

```yaml
description: Review and respond to scholia annotations on markdown documents. Use when asked to check comments, review scholia, or respond to annotations.
```

To:

```yaml
description: Review and respond to scholia annotations on markdown documents, or render rich agent responses (math, diagrams, code) in the browser. Use when asked to check comments, review scholia, respond to annotations, or when a response would benefit from rendered display.
```

- [ ] **Step 4: Add the render section to `agent-instructions.md`**

Append before the `## Configuration` section at the end:

```markdown
## Using scholia to render agent responses

When your response would contain display math, mermaid/TikZ diagrams, more than a few code blocks, long proofs or derivations, or complex tables, it may be easier for the user to read in the browser than in the terminal.

### When to suggest

Offer to render when your response includes:
- Display math (`$$...$$` or multi-line equations)
- Mermaid, TikZ, or other diagram markup
- More than ~3 code blocks
- Long proofs, derivations, or structured technical content
- Complex tables

Do **not** offer for short answers, single code snippets, plain prose, or conversational replies.

### How to suggest

Say something like:

> "This would be easier to read rendered in the browser — want me to open it with scholia?"

Wait for the user's confirmation before proceeding.

### How to render

1. Write your response to a temp markdown file with a descriptive name (e.g. `/tmp/scholia-cauchy-proof.md`). Include YAML frontmatter with at least `title:`.
2. Run `scholia view <path>` in the background.
3. Tell the user the file path and that it's open in the browser.

### Updating the rendered document

If the user asks for changes, edit the same file. The browser live-updates automatically — `scholia view` watches the file for changes and pushes new renders over WebSocket.

### Annotation loop

The user can select text in the browser and add comments in the sidebar. If they ask you to "check the scholia" (or similar), use `scholia list <path>` to read the annotations and respond — either by updating the file or replying to threads. This follows the same review workflow described above.

### Example

```
# Agent writes the response to a temp file:
cat /tmp/scholia-fourier-proof.md
---
title: Fourier Transform Proof
---

The Fourier transform of $f$ is defined as:

$$\hat{f}(\xi) = \int_{-\infty}^{\infty} f(x)\, e^{-2\pi i x \xi}\, dx$$

...

# Agent opens it:
scholia view /tmp/scholia-fourier-proof.md &
Scholia serving /tmp/scholia-fourier-proof.md at http://127.0.0.1:8088

# Later, user comments in the browser and asks agent to check:
scholia list /tmp/scholia-fourier-proof.md
a1b2
  scholia-fourier-proof.md:7:1-60
  ...
  [alice] Can you expand on why this integral converges?

scholia reply /tmp/scholia-fourier-proof.md a1b2 "Added convergence note." --author-ai-model "Claude Opus 4.6"
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/test_init.py -v`
Expected: all PASS (including new test and existing agent-agnostic test)

- [ ] **Step 6: Commit**

```bash
git add scholia/data/agent-instructions.md tests/test_init.py
git commit -m "Add 'Using scholia to render agent responses' to agent skill file"
```

---

### Task 5: Run full test suite

**Files:** none (verification only)

- [ ] **Step 1: Run all tests**

Run: `uv run pytest -v`
Expected: all PASS

- [ ] **Step 2: Manual smoke test — stdin**

Run: `echo '# Test\n\n$$E=mc^2$$' | scholia view - --title "Smoke test"`
Expected: browser opens, shows rendered math, stderr shows temp file path.
Press Ctrl+C to stop.

- [ ] **Step 3: Manual smoke test — piped-without-dash guard**

Run: `echo 'hello' | scholia view`
Expected: prints `Error: stdin is not a terminal — did you mean 'scholia view -'?` to stderr, exits non-zero.

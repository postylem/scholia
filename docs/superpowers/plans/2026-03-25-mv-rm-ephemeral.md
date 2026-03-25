# mv / rm / ephemeral Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `scholia mv`, `scholia rm`, ephemeral stdin cleanup, and a browser "Save as" button for managing document lifecycle.

**Architecture:** New `scholia/files.py` module for sidecar-aware move/remove operations. `_server` key in existing state file for server presence. `/api/relocate` endpoint on the server, reused by both CLI `mv` and browser "Save as". Ephemeral flag on ScholiaServer, cleared on relocate.

**Tech Stack:** Python stdlib (`shutil`, `os`), aiohttp (server routes + WS), existing test patterns (`subprocess.run`, `pytest-aiohttp`)

**Spec:** `docs/superpowers/specs/2026-03-25-mv-rm-ephemeral-design.md`

**Note:** Line numbers refer to the original unmodified files. They will shift as earlier tasks add lines.

---

### Task 1: `_server` state helpers

**Files:**
- Modify: `scholia/state.py`
- Create: `tests/test_server_state.py`

Add functions to read/write the `_server` key in the state file.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_server_state.py`:

```python
"""Tests for _server state key management."""
import os
from scholia.state import set_server, clear_server, get_server, load_state


def test_set_server_writes_key(tmp_path):
    doc = tmp_path / "doc.md"
    doc.write_text("# Hello")
    set_server(str(doc), port=8088, pid=12345)
    state = load_state(str(doc))
    assert state["_server"] == {"port": 8088, "pid": 12345}


def test_clear_server_removes_key(tmp_path):
    doc = tmp_path / "doc.md"
    doc.write_text("# Hello")
    set_server(str(doc), port=8088, pid=12345)
    clear_server(str(doc))
    state = load_state(str(doc))
    assert "_server" not in state


def test_clear_server_noop_when_missing(tmp_path):
    doc = tmp_path / "doc.md"
    doc.write_text("# Hello")
    # Should not raise
    clear_server(str(doc))


def test_get_server_returns_info(tmp_path):
    doc = tmp_path / "doc.md"
    doc.write_text("# Hello")
    set_server(str(doc), port=8088, pid=12345)
    info = get_server(str(doc))
    assert info == {"port": 8088, "pid": 12345}


def test_get_server_returns_none_when_missing(tmp_path):
    doc = tmp_path / "doc.md"
    doc.write_text("# Hello")
    assert get_server(str(doc)) is None


def test_set_server_preserves_annotation_state(tmp_path):
    """_server key should not clobber existing annotation read state."""
    doc = tmp_path / "doc.md"
    doc.write_text("# Hello")
    from scholia.state import mark_read
    mark_read(str(doc), "urn:uuid:test-id")
    set_server(str(doc), port=8088, pid=1)
    state = load_state(str(doc))
    assert "urn:uuid:test-id" in state
    assert "_server" in state
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_server_state.py -v`
Expected: FAIL (functions don't exist)

- [ ] **Step 3: Implement the helpers in `state.py`**

Add to the end of `scholia/state.py`:

```python
def set_server(doc_path: str | Path, port: int, pid: int):
    """Record that a scholia view server is running for this document."""
    state = load_state(doc_path)
    state["_server"] = {"port": port, "pid": pid}
    _write_state(doc_path, state)


def clear_server(doc_path: str | Path):
    """Remove server presence record."""
    state = load_state(doc_path)
    state.pop("_server", None)
    _write_state(doc_path, state)


def get_server(doc_path: str | Path) -> dict | None:
    """Return server info dict or None if no server is running."""
    state = load_state(doc_path)
    return state.get("_server")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_server_state.py -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add scholia/state.py tests/test_server_state.py
git commit -m "Add _server state helpers (set/clear/get) for server presence"
```

---

### Task 2: Server lifecycle — write/clear `_server` on start/exit

**Files:**
- Modify: `scholia/server.py:680-739` (`start` method)
- Test: `tests/test_server.py`

Wire the state helpers into ScholiaServer so `_server` is written on start and cleared on exit.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_server.py`:

```python
def test_server_writes_and_clears_server_state(tmp_path):
    """Server writes _server to state on start, clears on exit."""
    from scholia.state import get_server, state_path
    doc = tmp_path / "test.md"
    doc.write_text("# Hello")
    # State file shouldn't have _server before start
    assert get_server(str(doc)) is None
    # We can't easily test the full start/stop lifecycle in a unit test,
    # so test the methods directly
    server = ScholiaServer(str(doc))
    # Simulate what start() does
    server._register_server_state(8088)
    info = get_server(str(doc))
    assert info is not None
    assert info["port"] == 8088
    assert "pid" in info
    # Simulate what shutdown does
    server._clear_server_state()
    assert get_server(str(doc)) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_server.py::test_server_writes_and_clears_server_state -v`
Expected: FAIL (methods don't exist)

- [ ] **Step 3: Implement in `server.py`**

Add two methods to `ScholiaServer`:

```python
def _register_server_state(self, port: int):
    """Write _server key to state file."""
    from scholia.state import set_server
    set_server(self.doc_path, port=port, pid=os.getpid())

def _clear_server_state(self):
    """Remove _server key from state file."""
    from scholia.state import clear_server
    try:
        clear_server(self.doc_path)
    except Exception:
        pass  # Best effort — file may already be deleted (ephemeral)
```

Add `import os` to the top of `server.py` if not present.

In the `start()` method, after the port is determined (after `actual_port = ...`, around line 714), add:

```python
        self._register_server_state(actual_port)
```

At the end of `start()`, after the observer cleanup (after line 738), add in a `finally` block:

```python
        self._clear_server_state()
```

The full shutdown section of `start()` should become:

```python
        try:
            await stop_event.wait()
        finally:
            # Close all WebSocket connections
            for clients in list(self.ws_clients.values()):
                for ws in list(clients):
                    await ws.close()
            self.ws_clients.clear()
            self.ws_file.clear()
            self.ws_sidenotes.clear()

            # Stop all observers
            for observer in self._observers.values():
                observer.stop()
            for observer in self._observers.values():
                observer.join(timeout=1)
            self._observers.clear()
            self._observer_refcount.clear()

            self._clear_server_state()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_server.py::test_server_writes_and_clears_server_state -v`
Expected: PASS

- [ ] **Step 5: Run full test suite**

Run: `uv run pytest -v`
Expected: all PASS

- [ ] **Step 6: Commit**

```bash
git add scholia/server.py tests/test_server.py
git commit -m "Write _server state on server start, clear on exit"
```

---

### Task 3: Sidecar file operations module

**Files:**
- Create: `scholia/files.py`
- Create: `tests/test_files.py`

Shared helpers for moving/removing a document with its sidecars.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_files.py`:

```python
"""Tests for sidecar-aware file operations."""
import os
from pathlib import Path
from scholia.files import sidecar_paths, move_doc, remove_doc


def test_sidecar_paths_all_present(tmp_path):
    doc = tmp_path / "doc.md"
    doc.write_text("# Hello")
    jsonl = tmp_path / "doc.md.scholia.jsonl"
    jsonl.write_text("{}")
    state = tmp_path / "doc.md.scholia.state.json"
    state.write_text("{}")
    paths = sidecar_paths(str(doc))
    assert jsonl in paths
    assert state in paths


def test_sidecar_paths_none_present(tmp_path):
    doc = tmp_path / "doc.md"
    doc.write_text("# Hello")
    paths = sidecar_paths(str(doc))
    assert paths == []


def test_move_doc_with_sidecars(tmp_path):
    src = tmp_path / "src.md"
    src.write_text("# Hello")
    jsonl = tmp_path / "src.md.scholia.jsonl"
    jsonl.write_text('{"id":"test"}')
    state = tmp_path / "src.md.scholia.state.json"
    state.write_text('{}')

    dest = tmp_path / "sub" / "dest.md"
    dest.parent.mkdir()

    move_doc(str(src), str(dest))

    assert not src.exists()
    assert not jsonl.exists()
    assert not state.exists()
    assert dest.exists()
    assert (tmp_path / "sub" / "dest.md.scholia.jsonl").exists()
    assert (tmp_path / "sub" / "dest.md.scholia.state.json").exists()
    assert dest.read_text() == "# Hello"


def test_move_doc_no_sidecars(tmp_path):
    src = tmp_path / "src.md"
    src.write_text("# Hello")
    dest = tmp_path / "dest.md"
    move_doc(str(src), str(dest))
    assert not src.exists()
    assert dest.exists()


def test_move_doc_dest_exists_raises(tmp_path):
    src = tmp_path / "src.md"
    src.write_text("a")
    dest = tmp_path / "dest.md"
    dest.write_text("b")
    import pytest
    with pytest.raises(FileExistsError):
        move_doc(str(src), str(dest))


def test_move_doc_dest_exists_force(tmp_path):
    src = tmp_path / "src.md"
    src.write_text("a")
    dest = tmp_path / "dest.md"
    dest.write_text("b")
    move_doc(str(src), str(dest), force=True)
    assert dest.read_text() == "a"


def test_move_doc_source_missing_raises(tmp_path):
    import pytest
    with pytest.raises(FileNotFoundError):
        move_doc(str(tmp_path / "nope.md"), str(tmp_path / "dest.md"))


def test_remove_doc_with_sidecars(tmp_path):
    doc = tmp_path / "doc.md"
    doc.write_text("# Hello")
    jsonl = tmp_path / "doc.md.scholia.jsonl"
    jsonl.write_text("{}")
    state = tmp_path / "doc.md.scholia.state.json"
    state.write_text("{}")
    removed = remove_doc(str(doc))
    assert not doc.exists()
    assert not jsonl.exists()
    assert not state.exists()
    assert len(removed) == 3


def test_remove_doc_no_sidecars(tmp_path):
    doc = tmp_path / "doc.md"
    doc.write_text("# Hello")
    removed = remove_doc(str(doc))
    assert not doc.exists()
    assert len(removed) == 1


def test_remove_doc_missing_raises(tmp_path):
    import pytest
    with pytest.raises(FileNotFoundError):
        remove_doc(str(tmp_path / "nope.md"))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_files.py -v`
Expected: FAIL (module doesn't exist)

- [ ] **Step 3: Implement `scholia/files.py`**

```python
"""Sidecar-aware file operations (move, remove) for scholia documents."""

import shutil
from pathlib import Path

from scholia.comments import annotation_path
from scholia.state import state_path


def sidecar_paths(doc_path: str | Path) -> list[Path]:
    """Return list of existing sidecar files for a document."""
    sidecars = []
    ap = annotation_path(doc_path)
    if ap.exists():
        sidecars.append(ap)
    sp = state_path(doc_path)
    if sp.exists():
        sidecars.append(sp)
    return sidecars


def _dest_sidecar(src_sidecar: Path, src_doc: Path, dest_doc: Path) -> Path:
    """Compute destination path for a sidecar given src and dest doc paths."""
    # e.g. src.md.scholia.jsonl -> dest.md.scholia.jsonl
    suffix = str(src_sidecar.name)[len(src_doc.name):]
    return dest_doc.parent / f"{dest_doc.name}{suffix}"


def move_doc(src: str | Path, dest: str | Path, *, force: bool = False):
    """Move a document and its sidecars to a new location.

    Raises:
        FileNotFoundError: if source doesn't exist.
        FileExistsError: if destination exists and force is False.
    """
    src_path = Path(src).resolve()
    dest_path = Path(dest).resolve()

    if not src_path.exists():
        raise FileNotFoundError(f"Source not found: {src_path}")
    if dest_path.exists() and not force:
        raise FileExistsError(f"Destination already exists: {dest_path}")

    # Gather sidecars before moving
    sidecars = sidecar_paths(src)

    # Move the document
    shutil.move(str(src_path), str(dest_path))

    # Move each sidecar
    for sc in sidecars:
        dest_sc = _dest_sidecar(sc, src_path, dest_path)
        shutil.move(str(sc), str(dest_sc))


def remove_doc(doc_path: str | Path) -> list[Path]:
    """Remove a document and its sidecars. Return list of deleted paths.

    Raises:
        FileNotFoundError: if the document doesn't exist.
    """
    p = Path(doc_path).resolve()
    if not p.exists():
        raise FileNotFoundError(f"Document not found: {p}")

    removed = []
    sidecars = sidecar_paths(doc_path)

    p.unlink()
    removed.append(p)

    for sc in sidecars:
        sc.unlink()
        removed.append(sc)

    return removed
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_files.py -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add scholia/files.py tests/test_files.py
git commit -m "Add sidecar-aware move_doc and remove_doc helpers"
```

---

### Task 4: `scholia mv` CLI command + `/api/relocate` endpoint

**Files:**
- Modify: `scholia/cli.py` (add `cmd_mv` + argparse)
- Modify: `scholia/server.py` (add `/api/relocate` route)
- Create: `tests/test_mv.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_mv.py`:

```python
"""Tests for scholia mv command."""
import subprocess
import sys
from pathlib import Path


def test_mv_moves_doc_and_sidecars(tmp_path):
    src = tmp_path / "src.md"
    src.write_text("# Hello")
    jsonl = tmp_path / "src.md.scholia.jsonl"
    jsonl.write_text('{"id":"test"}\n')
    dest = tmp_path / "dest.md"

    result = subprocess.run(
        [sys.executable, "-m", "scholia.cli", "mv", str(src), str(dest)],
        capture_output=True, text=True,
    )
    assert result.returncode == 0
    assert not src.exists()
    assert dest.exists()
    assert (tmp_path / "dest.md.scholia.jsonl").exists()


def test_mv_dest_exists_errors(tmp_path):
    src = tmp_path / "src.md"
    src.write_text("a")
    dest = tmp_path / "dest.md"
    dest.write_text("b")

    result = subprocess.run(
        [sys.executable, "-m", "scholia.cli", "mv", str(src), str(dest)],
        capture_output=True, text=True,
    )
    assert result.returncode != 0
    assert "already exists" in result.stderr.lower()


def test_mv_dest_exists_force(tmp_path):
    src = tmp_path / "src.md"
    src.write_text("a")
    dest = tmp_path / "dest.md"
    dest.write_text("b")

    result = subprocess.run(
        [sys.executable, "-m", "scholia.cli", "mv", str(src), str(dest), "--force"],
        capture_output=True, text=True,
    )
    assert result.returncode == 0
    assert dest.read_text() == "a"


def test_mv_source_missing_errors(tmp_path):
    result = subprocess.run(
        [sys.executable, "-m", "scholia.cli", "mv",
         str(tmp_path / "nope.md"), str(tmp_path / "dest.md")],
        capture_output=True, text=True,
    )
    assert result.returncode != 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_mv.py -v`
Expected: FAIL

- [ ] **Step 3: Implement `cmd_mv` in `cli.py`**

Add the command function (above `cmd_skill_init`):

```python
def cmd_mv(args):
    import urllib.request
    import urllib.error
    from scholia.files import move_doc
    from scholia.state import get_server, clear_server

    src = args.source
    dest = args.dest
    force = args.force

    if not Path(src).exists():
        print(f"Error: source not found: {src}", file=sys.stderr)
        sys.exit(1)

    # Check if a server is running
    server_info = get_server(src)
    if server_info:
        port = server_info["port"]
        try:
            data = json.dumps({"to": dest, "force": force}).encode()
            req = urllib.request.Request(
                f"http://127.0.0.1:{port}/api/relocate",
                data=data,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                result = json.loads(resp.read())
                print(f"Moved to {result['path']} (server updated)")
                return
        except (urllib.error.URLError, OSError):
            # Server not reachable — stale _server key
            clear_server(src)

    # No server or server unreachable — move directly
    try:
        move_doc(src, dest, force=force)
    except FileExistsError:
        print(f"Error: destination already exists: {dest}", file=sys.stderr)
        print("Use --force to overwrite.", file=sys.stderr)
        sys.exit(1)
    print(f"Moved to {dest}")
```

Add argparse in `main()` (before the `skill-init` parser):

```python
    # mv
    p_mv = sub.add_parser(
        "mv",
        help="Move a document and its scholia sidecars",
    )
    p_mv.add_argument("source", help="Source markdown document path")
    p_mv.add_argument("dest", help="Destination path")
    p_mv.add_argument("--force", action="store_true",
                       help="Overwrite destination if it exists")
```

Add `"mv": cmd_mv` to the `handlers` dict.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_mv.py -v`
Expected: all PASS

- [ ] **Step 5: Implement `/api/relocate` in `server.py`**

Add to `_setup_routes`:

```python
        self.app.router.add_post("/api/relocate", self._handle_relocate)
```

Add `self._ephemeral = False` to `ScholiaServer.__init__` (we'll use this in Task 6).

Add a shared relocate helper method and the HTTP handler:

```python
    async def _do_relocate(self, dest_path: Path, force: bool = False):
        """Shared relocate logic used by both /api/relocate and WS save_as.

        Moves files, updates watcher, re-keys ws_clients/ws_file, clears
        ephemeral flag, broadcasts to all clients. Returns the response dict.

        Raises FileExistsError or FileNotFoundError on failure.
        """
        from scholia.files import move_doc
        from scholia.state import set_server

        old_path = self.doc_path
        move_doc(str(old_path), str(dest_path), force=force)

        # Update watcher
        self._stop_watching(old_path)
        self.doc_path = dest_path
        self.display_path = str(dest_path)
        self._start_watching(dest_path)

        # Re-key ws_clients from old_path to dest_path
        clients = self.ws_clients.pop(old_path, set())
        self.ws_clients.setdefault(dest_path, set()).update(clients)
        for c in clients:
            self.ws_file[c] = dest_path

        # Update _server in the new state file
        set_server(dest_path, port=self.port, pid=os.getpid())

        # Clear ephemeral flag (file was promoted)
        self._ephemeral = False

        response = {
            "type": "relocated",
            "path": str(dest_path),
            "display_path": self._display_path(dest_path),
        }

        # Broadcast to all connected clients
        msg = json.dumps(response)
        for ws_set in self.ws_clients.values():
            for ws in ws_set:
                try:
                    await ws.send_str(msg)
                except Exception:
                    pass

        return response

    async def _handle_relocate(self, request):
        """POST /api/relocate — move document + sidecars to a new path."""
        try:
            body = await request.json()
        except Exception:
            return web.json_response({"error": "Invalid JSON"}, status=400)

        dest = body.get("to")
        force = body.get("force", False)
        if not dest:
            return web.json_response({"error": "Missing 'to' field"}, status=400)

        try:
            result = await self._do_relocate(Path(dest).resolve(), force=force)
        except FileExistsError:
            return web.json_response(
                {"error": f"Destination already exists: {dest}"}, status=409)
        except FileNotFoundError as e:
            return web.json_response({"error": str(e)}, status=404)

        return web.json_response({"path": result["path"]})
```

- [ ] **Step 6: Add server relocate test**

Add to `tests/test_server.py`:

```python
@pytest.mark.asyncio
async def test_relocate_endpoint(aiohttp_client, tmp_path):
    """POST /api/relocate moves document and updates server."""
    doc = tmp_path / "src.md"
    doc.write_text("# Hello")
    jsonl = tmp_path / "src.md.scholia.jsonl"
    jsonl.write_text('{"id":"test"}\n')
    dest = tmp_path / "dest.md"

    server = ScholiaServer(str(doc))
    client = await aiohttp_client(server.app)

    resp = await client.post("/api/relocate", json={"to": str(dest)})
    assert resp.status == 200
    data = await resp.json()
    assert "dest.md" in data["path"]
    assert dest.exists()
    assert not doc.exists()
    assert (tmp_path / "dest.md.scholia.jsonl").exists()
```

- [ ] **Step 7: Run all tests**

Run: `uv run pytest -v`
Expected: all PASS

- [ ] **Step 8: Commit**

```bash
git add scholia/cli.py scholia/server.py tests/test_mv.py tests/test_server.py
git commit -m "Add scholia mv command and /api/relocate server endpoint"
```

---

### Task 5: `scholia rm` CLI command

**Files:**
- Modify: `scholia/cli.py`
- Create: `tests/test_rm.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_rm.py`:

```python
"""Tests for scholia rm command."""
import subprocess
import sys
from pathlib import Path


def test_rm_force_deletes_doc_and_sidecars(tmp_path):
    doc = tmp_path / "doc.md"
    doc.write_text("# Hello")
    jsonl = tmp_path / "doc.md.scholia.jsonl"
    jsonl.write_text("{}")
    state = tmp_path / "doc.md.scholia.state.json"
    state.write_text("{}")

    result = subprocess.run(
        [sys.executable, "-m", "scholia.cli", "rm", str(doc), "--force"],
        capture_output=True, text=True,
    )
    assert result.returncode == 0
    assert not doc.exists()
    assert not jsonl.exists()
    assert not state.exists()


def test_rm_force_no_sidecars(tmp_path):
    doc = tmp_path / "doc.md"
    doc.write_text("# Hello")

    result = subprocess.run(
        [sys.executable, "-m", "scholia.cli", "rm", str(doc), "--force"],
        capture_output=True, text=True,
    )
    assert result.returncode == 0
    assert not doc.exists()


def test_rm_missing_file_errors(tmp_path):
    result = subprocess.run(
        [sys.executable, "-m", "scholia.cli", "rm",
         str(tmp_path / "nope.md"), "--force"],
        capture_output=True, text=True,
    )
    assert result.returncode != 0


def test_rm_without_force_prompts(tmp_path):
    """Without --force, rm should prompt (and fail on non-interactive stdin)."""
    doc = tmp_path / "doc.md"
    doc.write_text("# Hello")

    result = subprocess.run(
        [sys.executable, "-m", "scholia.cli", "rm", str(doc)],
        input="n\n",
        capture_output=True, text=True,
    )
    # User said no — file should still exist
    assert doc.exists()


def test_rm_without_force_confirm_yes(tmp_path):
    doc = tmp_path / "doc.md"
    doc.write_text("# Hello")

    result = subprocess.run(
        [sys.executable, "-m", "scholia.cli", "rm", str(doc)],
        input="y\n",
        capture_output=True, text=True,
    )
    assert result.returncode == 0
    assert not doc.exists()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_rm.py -v`
Expected: FAIL

- [ ] **Step 3: Implement `cmd_rm` in `cli.py`**

Add the command function:

```python
def cmd_rm(args):
    from scholia.files import sidecar_paths, remove_doc
    from scholia.state import get_server

    doc = args.doc
    if not Path(doc).exists():
        print(f"Error: file not found: {doc}", file=sys.stderr)
        sys.exit(1)

    # Warn if server is running
    server_info = get_server(doc)
    if server_info:
        print("Warning: a scholia view server is watching this file.",
              file=sys.stderr)

    # Collect files that will be deleted
    files = [Path(doc).resolve()] + sidecar_paths(doc)

    if not args.force:
        print(f"Will delete {len(files)} file(s):")
        for f in files:
            print(f"  {f}")
        try:
            answer = input("Delete? [y/N] ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print("\nAborted.")
            sys.exit(1)
        if answer not in ("y", "yes"):
            print("Aborted.")
            return

    remove_doc(doc)
    if not args.force:
        print(f"Deleted {len(files)} file(s).")
```

Add argparse in `main()`:

```python
    # rm
    p_rm = sub.add_parser(
        "rm",
        help="Delete a document and its scholia sidecars",
    )
    p_rm.add_argument("doc", help="Markdown document path")
    p_rm.add_argument("--force", action="store_true",
                       help="Delete without confirmation prompt")
```

Add `"rm": cmd_rm` to the `handlers` dict.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_rm.py -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add scholia/cli.py tests/test_rm.py
git commit -m "Add scholia rm command for deleting doc + sidecars"
```

---

### Task 6: Ephemeral mode for stdin

**Files:**
- Modify: `scholia/cli.py` (add `--keep` flag, pass ephemeral to server)
- Modify: `scholia/server.py` (ephemeral cleanup on exit)
- Create: `tests/test_ephemeral.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_ephemeral.py`:

```python
"""Tests for ephemeral stdin mode."""
import os
from pathlib import Path
from scholia.server import ScholiaServer


def test_server_ephemeral_flag_default_false(tmp_path):
    doc = tmp_path / "doc.md"
    doc.write_text("# Hello")
    server = ScholiaServer(str(doc))
    assert server._ephemeral is False


def test_server_ephemeral_flag_settable(tmp_path):
    doc = tmp_path / "doc.md"
    doc.write_text("# Hello")
    server = ScholiaServer(str(doc), ephemeral=True)
    assert server._ephemeral is True


def test_ephemeral_cleanup_removes_files(tmp_path):
    """When ephemeral, cleanup should delete doc + sidecars."""
    doc = tmp_path / "doc.md"
    doc.write_text("# Hello")
    jsonl = tmp_path / "doc.md.scholia.jsonl"
    jsonl.write_text("{}")
    state = tmp_path / "doc.md.scholia.state.json"
    state.write_text("{}")

    server = ScholiaServer(str(doc), ephemeral=True)
    server._ephemeral_cleanup()

    assert not doc.exists()
    assert not jsonl.exists()
    assert not state.exists()


def test_non_ephemeral_cleanup_noop(tmp_path):
    """When not ephemeral, cleanup should not delete anything."""
    doc = tmp_path / "doc.md"
    doc.write_text("# Hello")

    server = ScholiaServer(str(doc), ephemeral=False)
    server._ephemeral_cleanup()

    assert doc.exists()


def test_relocate_clears_ephemeral(tmp_path):
    """Relocating (promoting) a file should clear the ephemeral flag."""
    doc = tmp_path / "doc.md"
    doc.write_text("# Hello")
    dest = tmp_path / "saved.md"

    server = ScholiaServer(str(doc), ephemeral=True)
    assert server._ephemeral is True

    # Simulate what _do_relocate does to the flag
    from scholia.files import move_doc
    move_doc(str(doc), str(dest))
    server.doc_path = dest.resolve()
    server._ephemeral = False  # This is what _do_relocate sets

    server._ephemeral_cleanup()
    # File should NOT be deleted — ephemeral was cleared
    assert dest.exists()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_ephemeral.py -v`
Expected: FAIL

- [ ] **Step 3: Implement ephemeral support**

In `ScholiaServer.__init__`, add `ephemeral` parameter:

```python
def __init__(self, doc_path: str, host: str = "127.0.0.1", port: int = 8088,
             ephemeral: bool = False):
```

And set `self._ephemeral = ephemeral` (replacing the `self._ephemeral = False` added in Task 4).

Add the cleanup method:

```python
def _ephemeral_cleanup(self):
    """Delete document and sidecars if in ephemeral mode."""
    if not self._ephemeral:
        return
    from scholia.files import remove_doc
    try:
        remove_doc(self.doc_path)
    except (FileNotFoundError, OSError):
        pass  # Already gone or permission issue
```

In `start()`, call `_ephemeral_cleanup()` after `_clear_server_state()` in the finally block:

```python
            self._clear_server_state()
            self._ephemeral_cleanup()
```

In `cli.py`, add `--keep` to the view subparser (after `--title`):

```python
    p_view.add_argument(
        "--keep", action="store_true",
        help="Keep stdin temp file after server exits (default: auto-cleanup)",
    )
```

Update `cmd_view` to pass `ephemeral` to the server. In the stdin branch:

```python
    if args.doc == "-":
        ...
        ephemeral = not args.keep
    else:
        if args.keep:
            print(
                "Warning: --keep is only used with stdin mode (scholia view -)",
                file=sys.stderr,
            )
        ephemeral = False
        ...

    server = ScholiaServer(doc, host=args.host, port=args.port, ephemeral=ephemeral)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_ephemeral.py -v`
Expected: all PASS

- [ ] **Step 5: Run full test suite**

Run: `uv run pytest -v`
Expected: all PASS

- [ ] **Step 6: Commit**

```bash
git add scholia/cli.py scholia/server.py tests/test_ephemeral.py
git commit -m "Add ephemeral mode: auto-cleanup stdin temp files on server exit"
```

---

### Task 7: Browser "Save as" button

**Files:**
- Modify: `scholia/server.py` (WS handler for `save_as`)
- Modify: `scholia/static/scholia.js` (menu item + modal)
- Modify: `tests/test_server.py`

This task adds the frontend "Save as..." button and its WebSocket handler. The server-side relocate logic was already implemented in Task 4.

- [ ] **Step 1: Write the failing server test**

Add to `tests/test_server.py`:

```python
@pytest.mark.asyncio
async def test_ws_save_as(aiohttp_client, tmp_path):
    """WebSocket save_as message triggers relocate."""
    doc = tmp_path / "src.md"
    doc.write_text("# Hello")
    dest = tmp_path / "saved.md"

    server = ScholiaServer(str(doc))
    client = await aiohttp_client(server.app)

    ws = await client.ws_connect("/ws")
    await ws.send_json({"type": "watch", "file": str(doc)})

    await ws.send_json({"type": "save_as", "path": str(dest)})
    msg = await ws.receive_json()
    assert msg["type"] == "relocated"
    assert "saved.md" in msg["path"]
    assert dest.exists()
    assert not doc.exists()

    await ws.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_server.py::test_ws_save_as -v`
Expected: FAIL

- [ ] **Step 3: Add `save_as` WebSocket handler in `server.py`**

In the WebSocket message handler (the `_handle_ws_message` method, where `msg` is the parsed JSON dict and `doc` is the local doc path variable), add a case for `save_as`. This reuses `_do_relocate` from Task 4:

```python
            elif msg_type == "save_as":
                dest = msg.get("path", "")
                if not dest:
                    await ws.send_json({"type": "error", "message": "Missing path"})
                    return
                try:
                    await self._do_relocate(Path(dest).resolve())
                except FileExistsError:
                    await ws.send_json({
                        "type": "error",
                        "message": f"Destination already exists: {dest}",
                    })
                except Exception as e:
                    await ws.send_json({"type": "error", "message": str(e)})
```

Note: `_do_relocate` handles all file moving, watcher updates, `ws_clients`/`ws_file` re-keying, ephemeral clearing, and broadcasting. No duplicated logic.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_server.py::test_ws_save_as -v`
Expected: PASS

- [ ] **Step 5: Add frontend "Save as" UI**

In `scholia/static/scholia.js`, in the `renderToolbar()` function where the Options menu items are built (near the Export PDF button, theme/typeface/footnote/zoom options):

Add a "Save as..." menu item that is only visible when the document path looks like a temp file. The check: `__SCHOLIA_DOC_FULLPATH__` contains `/scholia-` and is under a temp directory (starts with `/tmp/` or `/var/folders/`).

When clicked, show a modal with a text input pre-filled with a suggested path. The suggested path: take the document title from the `<h1>` or `<title>`, slugify it, prepend `~/Documents/`.

On submit, send `{type: "save_as", path: <value>}` via WebSocket. On receiving `{type: "relocated", ...}`, update the breadcrumb path and hide the "Save as..." option.

The exact frontend code is complex (modal creation, event handling, path suggestion logic) and should follow the existing patterns in scholia.js (e.g., how the Export PDF button and other modals work). The implementer should:

1. Find how the Options menu dropdown is built in `renderToolbar()`.
2. Add a "Save as..." item after "Export PDF", conditional on `isTempFile()`.
3. Create a `showSaveAsModal()` function similar to existing modal patterns.
4. Handle the `relocated` WS message type to update `__SCHOLIA_DOC_PATH__`, `__SCHOLIA_DOC_FULLPATH__`, the breadcrumb display, and remove the menu item.

- [ ] **Step 6: Run full test suite**

Run: `uv run pytest -v`
Expected: all PASS

- [ ] **Step 7: Commit**

```bash
git add scholia/server.py scholia/static/scholia.js tests/test_server.py
git commit -m "Add browser 'Save as' button for promoting temp files"
```

---

### Task 8: Update agent skill file

**Files:**
- Modify: `scholia/data/agent-instructions.md`

- [ ] **Step 1: Add `mv` and `rm` to CLI Reference**

In the "Setup" section of the CLI reference, add:

```markdown
### File management

```bash
# Move a document and its scholia sidecars
scholia mv <source.md> <dest.md>
scholia mv <source.md> <dest.md> --force  # overwrite destination

# Delete a document and its scholia sidecars
scholia rm <doc.md>
scholia rm <doc.md> --force  # skip confirmation prompt
```
```

- [ ] **Step 2: Update the "How to render" section**

In "Using scholia to render agent responses" → "How to render", add a note about saving:

After step 3, add:

```markdown
4. If the user wants to keep the rendered document, use `scholia mv` to promote it from `/tmp/` to a permanent location: `scholia mv /tmp/scholia-foo.md ~/notes/foo.md`. This moves the document and any annotations together, and transfers the running server to the new path.
```

- [ ] **Step 3: Run skill tests**

Run: `uv run pytest tests/test_init.py -v`
Expected: all PASS

- [ ] **Step 4: Commit**

```bash
git add scholia/data/agent-instructions.md
git commit -m "Add mv/rm to agent skill CLI reference and render workflow"
```

---

### Task 9: Full test suite + smoke tests

**Files:** none (verification only)

- [ ] **Step 1: Run all tests**

Run: `uv run pytest -v`
Expected: all PASS

- [ ] **Step 2: Smoke test — mv**

```bash
echo '# Test' > /tmp/scholia-test-mv.md
scholia mv /tmp/scholia-test-mv.md /tmp/scholia-test-moved.md
cat /tmp/scholia-test-moved.md  # should show "# Test"
ls /tmp/scholia-test-mv.md 2>&1  # should say "No such file"
rm /tmp/scholia-test-moved.md
```

- [ ] **Step 3: Smoke test — rm**

```bash
echo '# Test' > /tmp/scholia-test-rm.md
scholia rm /tmp/scholia-test-rm.md --force
ls /tmp/scholia-test-rm.md 2>&1  # should say "No such file"
```

- [ ] **Step 4: Smoke test — ephemeral**

```bash
echo '# Ephemeral test' | scholia view - --title "Ephemeral"
# Server starts, browser opens. Press Ctrl+C.
# The temp file should be deleted.
```

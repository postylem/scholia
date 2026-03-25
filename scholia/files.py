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

    sidecars = sidecar_paths(src)

    shutil.move(str(src_path), str(dest_path))

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

"""CLI: scholia view/list/show/reply/comment/edit/resolve/unresolve commands."""

import argparse
import asyncio
import json
import os
import sys
import tempfile
from datetime import datetime
from pathlib import Path

from scholia.comments import (
    append_comment,
    append_reply,
    edit_body,
    get_human_username,
    list_open,
    load_comments,
    resolve,
    resolve_id,
    short_id_map,
    unresolve,
)
from scholia.context import format_orphan_context, locate_anchor


# ── Format constants ────────────────────────────────────

FORMAT_CONTEXT = "context"         # messages + document context (default)
FORMAT_MESSAGES = "messages-only"  # messages without doc lookup
FORMAT_SUMMARY = "summary"         # one-line-per-thread overview
FORMAT_RAW = "raw"                 # raw JSONL selector fields + metadata
FORMAT_CHOICES = [FORMAT_CONTEXT, FORMAT_MESSAGES, FORMAT_SUMMARY, FORMAT_RAW]


# ── Display helpers ─────────────────────────────────────

def _use_color() -> bool:
    import os
    if os.environ.get("NO_COLOR"):
        return False
    if os.environ.get("FORCE_COLOR"):
        return True
    return hasattr(sys.stdout, "isatty") and sys.stdout.isatty()


def _author_color(creator: dict) -> str:
    """Return an ANSI color code for the author, or empty string if no color."""
    if not _use_color():
        return ""
    is_software = creator.get("type") == "Software"
    if is_software:
        return "\033[34m"  # blue for AI
    # Hash the name to a stable hue
    name = creator.get("name", "")
    h = 5381
    for ch in name:
        h = ((h << 5) + h + ord(ch)) & 0x7FFFFFFF
    hue = h % 6
    # Map to ANSI colors: 31=red, 32=green, 33=yellow, 35=magenta, 36=cyan, 91=bright red
    colors = ["\033[32m", "\033[33m", "\033[35m", "\033[36m", "\033[91m", "\033[31m"]
    return colors[hue]


_RESET = "\033[0m"


def _author_label(creator: dict) -> str:
    """Format a creator object as a display label."""
    name = creator.get("name", "?")
    nickname = creator.get("nickname", "")
    if nickname:
        return f"{name} ({nickname})"
    return name


def _print_annotation(ann, fmt=FORMAT_CONTEXT, doc_path=None, *,
                      short_id=None, show_status=True, ctx=None,
                      context_before=2, context_after=2):
    """Print a single annotation in the requested format."""
    selector = ann.get("target", {}).get("selector", {})
    exact = selector.get("exact", "")
    bodies = ann.get("body", [])
    n_msgs = len(bodies)
    last_author = _author_label(bodies[-1].get("creator", {})) if bodies else "?"

    if fmt == FORMAT_RAW:
        _print_raw(ann)
        return

    # Header line: [status] short_id (N messages)
    display_id = short_id or ann["id"]
    parts = []
    if show_status:
        status = ann.get("scholia:status", "?")
        parts.append(f"[{status}]")
    parts.append(display_id)
    if fmt != FORMAT_SUMMARY and n_msgs > 1:
        parts.append(f"({n_msgs} messages)")
    print(" ".join(parts))

    if fmt == FORMAT_SUMMARY:
        anchor_display = exact[:60] + ("\u2026" if len(exact) > 60 else "")
        print(f'  anchor: \u201c{anchor_display}\u201d')
        print(f"  {n_msgs} message(s), last by {last_author}")
        return

    # Context lookup (for FORMAT_CONTEXT)
    if fmt == FORMAT_CONTEXT and doc_path:
        if ctx is None:
            ctx = locate_anchor(doc_path, selector,
                                context_before=context_before,
                                context_after=context_after)
        if ctx["found"]:
            # File location reference
            loc = f"{doc_path}:{ctx['line']}:{ctx['col']}"
            if ctx["end_line"] != ctx["line"]:
                loc += f"-{ctx['end_line']}:{ctx['end_col']}"
            elif ctx["end_col"] != ctx["col"] + 1:
                loc += f"-{ctx['end_col']}"
            print(f"  {loc}")
            heading = ctx["heading"] or ""
            if heading:
                print(f"  in {heading}")
            for cline in (ctx["context_lines"] or []):
                print(cline)
        else:
            color = _use_color()
            warn = f"\033[33mwarning:\033[0m" if color else "warning:"
            print(f"  {warn} anchor text not found in document (orphaned)")
            print(f"  original context:")
            for line in format_orphan_context(selector):
                print(line)
    else:
        # FORMAT_MESSAGES or context without doc_path
        anchor_display = exact[:80] + ("\u2026" if len(exact) > 80 else "")
        print(f'  anchor: \u201c{anchor_display}\u201d')

    # Messages
    if bodies:
        print()
        for b in bodies:
            creator = b.get("creator", {})
            label = _author_label(creator)
            color = _author_color(creator)
            if color:
                print(f"  {color}[{label}]{_RESET} {b['value']}")
            else:
                print(f"  [{label}] {b['value']}")
    print()


def _print_raw(ann):
    """Print raw JSONL fields for an annotation."""
    selector = ann.get("target", {}).get("selector", {})
    print(f"id: {ann['id']}")
    print(f"status: {ann.get('scholia:status', '?')}")
    print(f"created: {ann.get('created', '?')}")
    if ann.get("modified"):
        print(f"modified: {ann['modified']}")
    print(f"creator: {json.dumps(ann.get('creator', {}))}")
    print(f"selector.exact: {selector.get('exact', '')}")
    print(f"selector.prefix: {selector.get('prefix', '')}")
    print(f"selector.suffix: {selector.get('suffix', '')}")
    bodies = ann.get("body", [])
    print(f"body: {len(bodies)} message(s)")
    for i, b in enumerate(bodies):
        label = _author_label(b.get("creator", {}))
        print(f"  [{i}] {label} ({b.get('created', '?')}): {b['value']}")
    print()


# ── File picker ─────────────────────────────────────────

def _default_new_filename() -> str:
    """Return 'notes.md' or 'notes_N.md' if notes.md already exists."""
    if not Path("notes.md").exists():
        return "notes.md"
    max_n = 0
    for f in Path.cwd().glob("notes_*.md"):
        try:
            n = int(f.stem.split("_", 1)[1])
            max_n = max(max_n, n)
        except (ValueError, IndexError):
            pass
    return f"notes_{max_n + 1}.md"


def _pick_or_create_doc() -> str:
    """Interactive file picker when no doc argument is given."""
    cwd = Path.cwd()
    md_files = sorted(cwd.glob("*.md"))
    choices = [f.name for f in md_files]

    if choices:
        print("Markdown files in current directory:\n")
        for i, name in enumerate(choices, 1):
            print(f"  {i}. {name}")
        print()
        while True:
            try:
                raw = input("Choose a file (number, name, or Enter to create new): ").strip()
            except (EOFError, KeyboardInterrupt):
                sys.exit(0)
            if raw == "":
                break  # fall through to create
            try:
                idx = int(raw)
                if 1 <= idx <= len(choices):
                    return choices[idx - 1]
            except ValueError:
                pass
            if raw in choices:
                return raw
            if raw and Path(raw).suffix == ".md":
                return raw
            print("Invalid choice. Try again.")
    default = _default_new_filename()
    try:
        name = input(f"New filename [{default}]: ").strip()
    except (EOFError, KeyboardInterrupt):
        sys.exit(0)
    if not name:
        name = default
    if not name.endswith(".md"):
        name += ".md"
    Path(name).write_text(
        f"---\ntitle: {Path(name).stem}\n---\n\n", encoding="utf-8"
    )
    print(f"Created {name}")
    return name


# ── Author resolution ───────────────────────────────────

def _resolve_author(args):
    """Resolve --author-ai-model / --author-name into (creator, nickname, is_software)."""
    model = getattr(args, "author_ai_model", None)
    name = getattr(args, "author_name", None)

    if model and name:
        print(
            "Error: --author-ai-model and --author-name are mutually exclusive.\n"
            "--author-name is for humans only. AI agents should use --author-ai-model.",
            file=sys.stderr,
        )
        sys.exit(1)

    if model:
        return "AI", model, True
    if name:
        return name, None, False
    return None, None, False


def _add_author_args(parser):
    """Add --author-ai-model and --author-name flags to a subparser."""
    parser.add_argument(
        "--author-ai-model", default=None, metavar="MODEL",
        help="AI model name and version (e.g. 'Opus 4.6'). Marks the comment as written by software.",
    )
    parser.add_argument(
        "--author-name", default=None,
        help="Human author name (default: SCHOLIA_USERNAME or system username)",
    )


def _add_format_arg(parser):
    """Add --format argument to a subparser."""
    parser.add_argument(
        "--format", dest="fmt", default=FORMAT_CONTEXT,
        choices=FORMAT_CHOICES, metavar="FORMAT",
        help=f"Output format: {', '.join(FORMAT_CHOICES)} (default: context)",
    )


# ── Commands ────────────────────────────────────────────

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
        ephemeral = not args.keep
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
        if args.keep:
            print(
                "Warning: --keep is only used with stdin mode (scholia view -)",
                file=sys.stderr,
            )
        doc = args.doc or _pick_or_create_doc()
        ephemeral = False

    server = ScholiaServer(doc, host=args.host, port=args.port, ephemeral=ephemeral)
    try:
        asyncio.run(server.start())
    except (KeyboardInterrupt, SystemExit):
        pass


def _check_doc_exists(doc_path: str):
    """Exit with error if the document doesn't exist."""
    if not Path(doc_path).exists():
        print(f"Error: file not found: {doc_path}", file=sys.stderr)
        sys.exit(1)


def cmd_list(args):
    _check_doc_exists(args.doc)
    since = None
    if args.since:
        try:
            since = datetime.fromisoformat(args.since)
        except ValueError:
            try:
                since = datetime.strptime(args.since, "%Y-%m-%d")
            except ValueError:
                print(f"Error: invalid date format '{args.since}', use YYYY-MM-DD", file=sys.stderr)
                sys.exit(1)

    if args.all:
        items = load_comments(args.doc)
    else:
        items = list_open(args.doc)

    if since:
        filtered = []
        for ann in items:
            ann_time = ann.get("modified") or ann.get("created", "")
            try:
                if datetime.fromisoformat(ann_time) >= since:
                    filtered.append(ann)
            except (ValueError, TypeError):
                filtered.append(ann)
        items = filtered

    if not items:
        print("No comments.")
        return

    id_map = short_id_map(args.doc)
    context_before, context_after = args.context
    if context_before < 0 or context_after < 0:
        print("Error: --context values must be non-negative", file=sys.stderr)
        sys.exit(1)
    show_status = args.all

    if args.fmt == FORMAT_CONTEXT and args.doc:
        anchored = []
        orphaned = []
        for ann in items:
            selector = ann.get("target", {}).get("selector", {})
            ctx = locate_anchor(args.doc, selector,
                                context_before=context_before,
                                context_after=context_after)
            if ctx["found"]:
                anchored.append((ann, ctx))
            else:
                orphaned.append(ann)
        anchored.sort(key=lambda pair: pair[1]["line"])
        for ann, ctx in anchored:
            _print_annotation(ann, fmt=args.fmt, doc_path=args.doc,
                              short_id=id_map.get(ann["id"]),
                              show_status=show_status, ctx=ctx)
        if orphaned:
            print(f"── orphaned threads ({len(orphaned)}) ──\n")
            for ann in orphaned:
                _print_annotation(ann, fmt=args.fmt, doc_path=args.doc,
                                  short_id=id_map.get(ann["id"]),
                                  show_status=show_status,
                                  context_before=context_before,
                                  context_after=context_after)
    else:
        for ann in items:
            _print_annotation(ann, fmt=args.fmt, doc_path=args.doc,
                              short_id=id_map.get(ann["id"]),
                              show_status=show_status)


def cmd_show(args):
    _check_doc_exists(args.doc)
    full_id = resolve_id(args.doc, args.id)
    comments = load_comments(args.doc)
    id_map = short_id_map(args.doc)
    context_before, context_after = args.context
    if context_before < 0 or context_after < 0:
        print("Error: --context values must be non-negative", file=sys.stderr)
        sys.exit(1)
    for ann in comments:
        if ann["id"] == full_id:
            _print_annotation(ann, fmt=args.fmt, doc_path=args.doc,
                              short_id=id_map.get(ann["id"]),
                              show_status=True,
                              context_before=context_before,
                              context_after=context_after)
            return


def cmd_reply(args):
    full_id = resolve_id(args.doc, args.id)
    creator, nickname, is_software = _resolve_author(args)
    ann = append_reply(
        args.doc, full_id, args.text,
        creator=creator, nickname=nickname, is_software=is_software,
    )
    if not args.quiet:
        print(f"Reply added to {ann['id']}")


def cmd_edit(args):
    full_id = resolve_id(args.doc, args.id)
    ann = edit_body(args.doc, full_id, args.text)
    if not args.quiet:
        print(f"Edited last message in {ann['id']}")


def cmd_comment(args):
    creator, nickname, is_software = _resolve_author(args)
    ann = append_comment(
        args.doc, exact=args.anchor, body_text=args.text,
        creator=creator, nickname=nickname, is_software=is_software,
    )
    if not args.quiet:
        print(f"Comment created: {ann['id']}")


def cmd_resolve(args):
    from scholia.state import mark_read

    full_id = resolve_id(args.doc, args.id)
    resolved = resolve(args.doc, full_id)
    mark_read(args.doc, resolved["id"])
    if not args.quiet:
        print(f"Resolved {resolved['id']}")


def cmd_unresolve(args):
    full_id = resolve_id(args.doc, args.id)
    unresolved = unresolve(args.doc, full_id)
    if not args.quiet:
        print(f"Unresolved {unresolved['id']}")


def cmd_export(args):
    from scholia.server import _render_export_sync
    import subprocess

    doc = Path(args.doc)
    if not doc.exists():
        print(f"Error: file not found: {args.doc}", file=sys.stderr)
        sys.exit(1)

    doc = doc.resolve()
    fmt = args.to

    if args.output:
        output = Path(args.output)
    else:
        ext_map = {"pdf": ".pdf", "html": ".html", "latex": ".tex"}
        output = Path.cwd() / (doc.stem + ext_map[fmt])

    try:
        _render_export_sync(doc, fmt, output, pdf_engine=args.pdf_engine)
    except subprocess.CalledProcessError as e:
        stderr_text = e.stderr.decode() if isinstance(e.stderr, bytes) else (e.stderr or str(e))
        if fmt == "pdf" and ("latex" in stderr_text.lower() or "pdf" in stderr_text.lower()):
            print(
                "Error: PDF export requires a LaTeX engine (xelatex, tectonic, etc.).\n"
                "Install one, or use --to html or --to latex instead.",
                file=sys.stderr,
            )
        else:
            print(f"Error: export failed: {stderr_text}", file=sys.stderr)
        sys.exit(1)

    print(output)


def cmd_rm(args):
    from scholia.files import sidecar_paths, remove_doc
    from scholia.state import get_server

    doc = args.doc
    if not Path(doc).exists():
        print(f"Error: file not found: {doc}", file=sys.stderr)
        sys.exit(1)

    server_info = get_server(doc)
    if server_info:
        print("Warning: a scholia view server is watching this file.",
              file=sys.stderr)

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


# ── Skill init ──────────────────────────────────────────

def _load_instruction_template() -> str:
    """Load the bundled agent instruction template."""
    template_path = Path(__file__).parent / "data" / "agent-instructions.md"
    return template_path.read_text(encoding="utf-8")


def _find_gitignore() -> Path | None:
    """Find .gitignore in cwd or git root, if any."""
    cwd = Path.cwd()
    gi = cwd / ".gitignore"
    if gi.exists():
        return gi
    for parent in cwd.parents:
        if (parent / ".git").exists():
            gi = parent / ".gitignore"
            return gi if gi.exists() else None
        if parent == parent.parent:
            break
    return None


_GITIGNORE_SNIPPET = """\
# Scholia sidecar files
*.scholia.state.json
# *.scholia.jsonl
"""


def _offer_gitignore():
    """Offer to append scholia patterns to .gitignore."""
    gi = _find_gitignore()
    if gi is None:
        return
    content = gi.read_text(encoding="utf-8")
    if "*.scholia.state.json" in content:
        return
    try:
        answer = input(f"Add scholia patterns to {gi}? [Y/n] ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        return
    if answer in ("", "y", "yes"):
        with open(gi, "a", encoding="utf-8") as f:
            if not content.endswith("\n"):
                f.write("\n")
            f.write(_GITIGNORE_SNIPPET)
        print(f"Updated {gi}")


def cmd_skill_init(args):
    if args.path:
        path = Path(args.path).expanduser()
        if not path.is_absolute():
            path = Path.cwd() / path
    else:
        path = Path.home() / ".claude" / "skills" / "scholia" / "SKILL.md"

    if path.exists() and not args.force:
        print(f"Already exists: {path}")
        print("Use --force to overwrite.")
        return

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_load_instruction_template(), encoding="utf-8")
    print(f"Wrote {path}")
    print("This file teaches your AI coding agent how to use scholia.")

    _offer_gitignore()


# ── Main ────────────────────────────────────────────────

def main():
    from scholia import __version__

    parser = argparse.ArgumentParser(
        prog="scholia",
        description="Margin annotations for markdown documents. "
        "Add comments anchored to specific text, collaborate in threaded "
        "discussions, and review with AI agents via CLI or browser.",
    )
    parser.add_argument(
        "--version", action="version", version=f"scholia {__version__}"
    )
    sub = parser.add_subparsers(dest="command")

    # view
    p_view = sub.add_parser(
        "view",
        help="Launch a live-rendering server and open the document in a browser",
    )
    p_view.add_argument(
        "doc", nargs="?", default=None,
        help="Markdown document path (interactive picker if omitted)",
    )
    p_view.add_argument(
        "--host", default="127.0.0.1",
        help="Server bind address (default: 127.0.0.1)",
    )
    p_view.add_argument(
        "--port", type=int, default=8088,
        help="Server port (default: 8088)",
    )
    p_view.add_argument(
        "--title", default=None,
        help="Document title (YAML frontmatter, only used with stdin '-')",
    )
    p_view.add_argument(
        "--keep", action="store_true",
        help="Keep stdin temp file after server exits (default: auto-cleanup)",
    )

    # list
    p_list = sub.add_parser(
        "list",
        help="List open annotation threads (with messages and document context)",
    )
    p_list.add_argument("doc", help="Markdown document path")
    p_list.add_argument(
        "--all", action="store_true",
        help="Include resolved threads (default: open only)",
    )
    p_list.add_argument(
        "--since", metavar="DATE",
        help="Filter to threads modified since DATE (YYYY-MM-DD)",
    )
    _add_format_arg(p_list)
    p_list.add_argument(
        "--context", nargs=2, type=int, default=[2, 2],
        metavar=("BEFORE", "AFTER"),
        help="Lines of context before/after anchor (default: 2 2)",
    )

    # show
    p_show = sub.add_parser(
        "show",
        help="Show a single annotation thread with document context",
    )
    p_show.add_argument("doc", help="Markdown document path")
    p_show.add_argument("id", help="Annotation ID or unique prefix (e.g. full urn:uuid:..., or just 'a72')")
    _add_format_arg(p_show)
    p_show.add_argument(
        "--context", nargs=2, type=int, default=[2, 2],
        metavar=("BEFORE", "AFTER"),
        help="Lines of context before/after anchor (default: 2 2)",
    )

    # reply
    p_reply = sub.add_parser("reply", help="Reply to an annotation thread")
    p_reply.add_argument("doc", help="Markdown document path")
    p_reply.add_argument("id", help="Annotation ID or unique prefix (e.g. full urn:uuid:..., or just 'a72')")
    p_reply.add_argument("text", help="Reply text")
    p_reply.add_argument("-q", "--quiet", action="store_true", help="Suppress confirmation output")
    _add_author_args(p_reply)

    # comment
    p_comment = sub.add_parser(
        "comment",
        help="Add a new comment anchored to text in the document",
    )
    p_comment.add_argument("doc", help="Markdown document path")
    p_comment.add_argument(
        "anchor",
        help="Exact text from the document to anchor the comment to",
    )
    p_comment.add_argument("text", help="Comment text")
    p_comment.add_argument("-q", "--quiet", action="store_true", help="Suppress confirmation output")
    _add_author_args(p_comment)

    # edit
    p_edit = sub.add_parser(
        "edit",
        help="Edit the last message in a thread (your own messages only)",
    )
    p_edit.add_argument("doc", help="Markdown document path")
    p_edit.add_argument("id", help="Annotation ID or unique prefix (e.g. full urn:uuid:..., or just 'a72')")
    p_edit.add_argument("text", help="Replacement text for the last message")
    p_edit.add_argument("-q", "--quiet", action="store_true", help="Suppress confirmation output")

    # resolve
    p_resolve = sub.add_parser("resolve", help="Mark a thread as resolved (closed)")
    p_resolve.add_argument("doc", help="Markdown document path")
    p_resolve.add_argument("id", help="Annotation ID or unique prefix (e.g. full urn:uuid:..., or just 'a72')")
    p_resolve.add_argument("-q", "--quiet", action="store_true", help="Suppress confirmation output")

    # unresolve
    p_unresolve = sub.add_parser("unresolve", help="Reopen a resolved thread")
    p_unresolve.add_argument("doc", help="Markdown document path")
    p_unresolve.add_argument("id", help="Annotation ID or unique prefix (e.g. full urn:uuid:..., or just 'a72')")
    p_unresolve.add_argument("-q", "--quiet", action="store_true", help="Suppress confirmation output")

    # export
    p_export = sub.add_parser(
        "export",
        help="Export document to PDF, standalone HTML, or LaTeX",
    )
    p_export.add_argument("doc", help="Markdown document path")
    p_export.add_argument(
        "--to", "-t", default="pdf", choices=["pdf", "html", "latex"],
        help="Output format (default: pdf)",
    )
    p_export.add_argument(
        "--output", "-o", default=None, metavar="PATH",
        help="Output file path (default: <input-stem>.<ext> in cwd)",
    )
    p_export.add_argument(
        "--pdf-engine", default=None, metavar="ENGINE",
        help="LaTeX engine for PDF output (e.g. xelatex, tectonic)",
    )

    # mv
    p_mv = sub.add_parser(
        "mv",
        help="Move a document and its scholia sidecars",
    )
    p_mv.add_argument("source", help="Source markdown document path")
    p_mv.add_argument("dest", help="Destination path")
    p_mv.add_argument("--force", action="store_true",
                       help="Overwrite destination if it exists")

    # rm
    p_rm = sub.add_parser(
        "rm",
        help="Delete a document and its scholia sidecars",
    )
    p_rm.add_argument("doc", help="Markdown document path")
    p_rm.add_argument("--force", action="store_true",
                       help="Delete without confirmation prompt")

    # skill-init
    p_skill = sub.add_parser(
        "skill-init",
        help="Install an AI agent skill file that teaches your coding agent how to use scholia",
    )
    p_skill.add_argument(
        "path", nargs="?", default=None,
        help="Target file path (default: ~/.claude/skills/scholia/SKILL.md)",
    )
    p_skill.add_argument("--force", action="store_true", help="Overwrite existing file")

    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        sys.exit(0)

    handlers = {
        "view": cmd_view,
        "reply": cmd_reply,
        "list": cmd_list,
        "show": cmd_show,
        "comment": cmd_comment,
        "edit": cmd_edit,
        "skill-init": cmd_skill_init,
        "resolve": cmd_resolve,
        "unresolve": cmd_unresolve,
        "export": cmd_export,
        "mv": cmd_mv,
        "rm": cmd_rm,
    }

    try:
        handlers[args.command](args)
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    except RuntimeError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

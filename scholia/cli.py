"""CLI: scholia start/reply/list/comment/resolve/unresolve commands."""

import argparse
import asyncio
import sys
from datetime import datetime
from pathlib import Path

from scholia.comments import (
    append_comment,
    append_reply,
    get_default_creator,
    list_open,
    load_comments,
    resolve,
    unresolve,
)


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
            # Try as number
            try:
                idx = int(raw)
                if 1 <= idx <= len(choices):
                    return choices[idx - 1]
            except ValueError:
                pass
            # Try as filename
            if raw in choices:
                return raw
            if raw and Path(raw).suffix == ".md":
                return raw  # user typed a new name
            print("Invalid choice. Try again.")
    # Create new file
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


def cmd_view(args):
    from scholia.server import ScholiaServer

    doc = args.doc or _pick_or_create_doc()
    server = ScholiaServer(doc, host=args.host, port=args.port)
    try:
        asyncio.run(server.start())
    except KeyboardInterrupt:
        pass


def cmd_reply(args):
    ann = append_reply(args.doc, args.id, args.text, creator=args.creator)
    print(f"Reply added to {ann['id']}")


def cmd_list(args):
    # Parse --since if provided
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

    # Get comments based on --open/--all flags
    if args.all or args.since:
        items = load_comments(args.doc)
    elif args.open:
        items = list_open(args.doc)
    else:
        items = list_open(args.doc)

    # Apply --since filter
    if since:
        filtered = []
        for ann in items:
            ann_time = ann.get("modified") or ann.get("created", "")
            try:
                if datetime.fromisoformat(ann_time) >= since:
                    filtered.append(ann)
            except (ValueError, TypeError):
                filtered.append(ann)  # include if we can't parse
        items = filtered

    if not items:
        print("No comments.")
        return

    for ann in items:
        status = ann.get("scholia:status", "?")
        anchor = ann["target"]["selector"]["exact"][:60]
        bodies = ann.get("body", [])
        n_msgs = len(bodies)
        last_author = bodies[-1]["creator"]["name"] if bodies else "?"
        print(f"[{status}] {ann['id']}")
        print(f'  anchor: "{anchor}"')
        print(f"  {n_msgs} message(s), last by {last_author}")
        print()


def cmd_comment(args):
    ann = append_comment(
        args.doc, exact=args.anchor, body_text=args.text, creator=args.creator
    )
    print(f"Comment created: {ann['id']}")


def _load_instruction_template() -> str:
    """Load the bundled agent instruction template."""
    template_path = Path(__file__).parent / "data" / "agent-instructions.md"
    return template_path.read_text(encoding="utf-8")


def cmd_skill_init(args):
    if args.path:
        path = Path(args.path).expanduser()
        if not path.is_absolute():
            path = Path.cwd() / path
    else:
        path = Path.home() / ".claude" / "skills" / "scholia.md"

    if path.exists() and not args.force:
        print(f"Already exists: {path}")
        print("Use --force to overwrite.")
        return

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_load_instruction_template(), encoding="utf-8")
    print(f"Wrote {path}")
    print("This file teaches your AI coding agent how to use scholia.")


def cmd_resolve(args):
    resolved = resolve(args.doc, args.id)
    print(f"Resolved {resolved['id']}")


def cmd_unresolve(args):
    unresolved = unresolve(args.doc, args.id)
    print(f"Unresolved {unresolved['id']}")


def main():
    parser = argparse.ArgumentParser(
        prog="scholia",
        description="Collaborative marginalia for human-AI dialogue",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # view
    p_view = sub.add_parser("view", help="View and annotate a document")
    p_view.add_argument(
        "doc",
        nargs="?",
        default=None,
        help="Markdown document path (interactive picker if omitted)",
    )
    p_view.add_argument("--host", default="127.0.0.1")
    p_view.add_argument("--port", type=int, default=8088)

    # reply
    p_reply = sub.add_parser("reply", help="Reply to an annotation")
    p_reply.add_argument("doc", help="Markdown document path")
    p_reply.add_argument("id", help="Annotation ID")
    p_reply.add_argument("text", help="Reply text")
    p_reply.add_argument("--creator", default="ai")

    # list
    p_list = sub.add_parser("list", help="List annotations")
    p_list.add_argument("doc", help="Markdown document path")
    p_list.add_argument("--open", action="store_true", help="Only show open annotations")
    p_list.add_argument("--all", action="store_true", help="Show all including resolved")
    p_list.add_argument("--since", help="Show annotations since date (YYYY-MM-DD)")

    # comment
    p_comment = sub.add_parser("comment", help="Add a new comment")
    p_comment.add_argument("doc", help="Markdown document path")
    p_comment.add_argument("anchor", help="Text to anchor the comment to")
    p_comment.add_argument("text", help="Comment text")
    p_comment.add_argument("--creator", default=None)

    # skill-init
    p_skill = sub.add_parser("skill-init", help="Install or update agent skill file")
    p_skill.add_argument(
        "path",
        nargs="?",
        default=None,
        help="Target path (default: ~/.claude/skills/scholia.md)",
    )
    p_skill.add_argument("--force", action="store_true", help="Overwrite existing file")

    # resolve
    p_resolve = sub.add_parser("resolve", help="Resolve a thread")
    p_resolve.add_argument("doc", help="Markdown document path")
    p_resolve.add_argument("id", help="Annotation ID")

    # unresolve
    p_unresolve = sub.add_parser("unresolve", help="Unresolve a thread")
    p_unresolve.add_argument("doc", help="Markdown document path")
    p_unresolve.add_argument("id", help="Annotation ID")

    args = parser.parse_args()

    handlers = {
        "view": cmd_view,
        "reply": cmd_reply,
        "list": cmd_list,
        "comment": cmd_comment,
        "skill-init": cmd_skill_init,
        "resolve": cmd_resolve,
        "unresolve": cmd_unresolve,
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

"""CLI: scholia start/reply/list/comment commands."""

import argparse
import asyncio
import sys

from scholia.comments import append_comment, append_reply, list_open, load_comments
from scholia.server import ScholiaServer


def cmd_start(args):
    server = ScholiaServer(args.doc, host=args.host, port=args.port)
    try:
        asyncio.run(server.start())
    except KeyboardInterrupt:
        pass


def cmd_reply(args):
    ann = append_reply(args.doc, args.id, args.text, creator=args.creator)
    print(f"Reply added to {ann['id']}")


def cmd_list(args):
    if args.open:
        items = list_open(args.doc)
    else:
        items = load_comments(args.doc)

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


def main():
    parser = argparse.ArgumentParser(
        prog="scholia",
        description="Collaborative document annotation for human-AI dialogue",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # start
    p_start = sub.add_parser("start", help="Start annotation server")
    p_start.add_argument("doc", help="Markdown document path")
    p_start.add_argument("--host", default="127.0.0.1")
    p_start.add_argument("--port", type=int, default=8088)

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

    # comment
    p_comment = sub.add_parser("comment", help="Add a new comment")
    p_comment.add_argument("doc", help="Markdown document path")
    p_comment.add_argument("anchor", help="Text to anchor the comment to")
    p_comment.add_argument("text", help="Comment text")
    p_comment.add_argument("--creator", default="human")

    args = parser.parse_args()

    handlers = {
        "start": cmd_start,
        "reply": cmd_reply,
        "list": cmd_list,
        "comment": cmd_comment,
    }
    handlers[args.command](args)


if __name__ == "__main__":
    main()

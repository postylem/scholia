# Scholia

Collaborative document annotation for human-AI dialogue. Write in your editor, comment in the browser, review with your AI assistant.

## Prerequisites

- Python 3.10+
- [Pandoc](https://pandoc.org/installing.html)

## Install

```bash
# From source
pipx install .
# or
uv tool install .

# From git
pipx install git+https://github.com/<user>/scholia.git
```

## Quick Start

```bash
# Start the annotation server
scholia start paper.md

# Open http://127.0.0.1:8088 in your browser
# Select text in the document to add comments
```

## AI Agent Setup

Scholia works with any AI coding agent. Run `scholia init` to add review instructions to your project:

```bash
# Claude Code (default)
scholia init

# Cursor
scholia init .cursor/rules/scholia.md

# Codex
scholia init AGENTS.md

# opencode (https://opencode.ai/docs/skills/)
scholia init .opencode/skills/scholia.md

# Global install (always available, not per-project)
scholia init --global
```

This writes a single markdown file containing the CLI commands and review workflow your agent needs. The file is self-contained — inspect it to see exactly what your agent will be told. Run `scholia init --force` to update it after upgrading scholia.

## CLI Reference

```
scholia start <doc.md>                    Start annotation server
scholia start <doc.md> --port 0           Auto-pick a free port
scholia list <doc.md> --open              List open comments
scholia list <doc.md> --all               List all comments
scholia reply <doc.md> <id> "text"        Reply to a comment
scholia comment <doc.md> "anchor" "text"  Add a new comment
scholia resolve <doc.md> <id>             Resolve a thread
scholia unresolve <doc.md> <id>           Reopen a thread
scholia init [path]                       Write agent instructions
scholia init --global [path]              Write to home directory
```

## How It Works

- You edit `.md` files in your editor
- The browser shows a live-rendered view with a comment sidebar
- Comments are stored in `<doc>.md.scholia.jsonl` (append-only, W3C Web Annotation format)
- File changes are detected via watchdog and pushed to the browser via WebSocket
- Your AI assistant reads and replies to comments via the CLI

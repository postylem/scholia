---
title: Scholia
subtitle: Human-AI dialogue via collaborative marginalia
---

# Scholia

Take notes in the margins of live-rendered rich text documents, and collaborate in comment threads with an AI assistant.

Think of notes added to manuscripts by medieval scholars annotating clarifications, corrections, and arguments threaded alongside the original text. This is a tool for maintaining such marginalia, and (optionally) using them to collaborate with an AI interlocutor as the document evolves.


## How It Works

You edit `.md` files in your editor. The browser shows a live-rendered view with a comment sidebar. Select any text to start a conversation about it.

Comments are stored in a sidecar file (`<doc>.md.scholia.jsonl`) using the W3C Web Annotation format. File changes are detected via watchdog and pushed to the browser via WebSocket, so the rendered view updates as you type.

Your AI assistant reads and replies to comments via the CLI:

```bash
# List open comments
scholia list paper.md --open

# Reply to a thread
scholia reply paper.md <annotation-id> "Your reply here"

# Add a new comment anchored to text
scholia comment paper.md "exact text" "Your comment"
```

## AI Agent Setup

Scholia works with any AI coding agent. Run `scholia init` to write review instructions into your project:

```bash
# Claude Code (default)
scholia init

# Cursor
scholia init .cursor/rules/scholia.md

# Codex
scholia init AGENTS.md
```

This writes a single markdown file that teaches your agent the CLI commands and review workflow. The file is self-contained — inspect it to see exactly what your agent will be told.

## Install

Requires Python 3.10+ and [Pandoc](https://pandoc.org/installing.html).

```bash
pipx install .
# or
uv tool install .
```

Then start annotating:

```bash
scholia start paper.md
```

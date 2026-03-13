# Scholia: Collaborative Document Annotation for Human-AI Dialogue

**Date:** 2026-03-12
**Status:** Beta v0.1 design
**Author:** V + Claude
**Builds on:** NA. First version.

## 1. Problem

When working with an AI assistant on complex topics (math, algorithms, code), the output often lands in a markdown file for careful reading. The current feedback loop is awkward: read the rendered document, switch to the terminal, verbally reference specific passages, get a response, repeat. There's no way to anchor comments to specific text or maintain threaded discussions in the margins.

## 2. Solution

Scholia is a collaborative annotation system that renders a markdown document in the browser with a comment sidebar, enabling threaded marginal dialogue between a human and an AI assistant.

**Core interaction model:**
- Human edits `.md` in their editor; the browser shows a live-rendered read-only view
- Human selects text in the browser to create anchored comment threads in a sidebar
- AI reviews and replies to comments via CLI commands (`scholia reply`, `scholia list`)
- File watcher detects changes to both the `.md` file and the `.scholia.jsonl` comment store, pushing live updates over WebSocket

## 3. Architecture

```
┌─────────────┐     ┌──────────────────┐     ┌─────────────┐
│  Editor      │────▶│  .md file        │◀────│  AI (CLI)   │
│  (human)     │     └────────┬─────────┘     └──────┬──────┘
└─────────────┘              │                       │
                    watchdog │              scholia reply
                             ▼                       │
                    ┌────────────────┐               │
                    │ Scholia Server │               │
                    │  (Python/aio)  │◀──────────────┘
                    │                │
                    │ • Pandoc render│     ┌──────────────────┐
                    │ • File watch   │────▶│ .scholia.jsonl   │
                    │ • WebSocket    │     └──────────────────┘
                    └───────┬────────┘
                       HTTP │ WS
                            ▼
                    ┌────────────────┐
                    │   Browser      │
                    │ • Rendered doc │
                    │ • Sidebar      │
                    │ • Anchoring    │
                    └────────────────┘
```

**Single-process Python server** using asyncio, aiohttp (HTTP + WebSocket), watchdog (file observation), and Pandoc (markdown → HTML).

## 4. Data Model

Comments are stored in `<docname>.scholia.jsonl` using the [W3C Web Annotation](https://www.w3.org/TR/annotation-model/) data model with `TextQuoteSelector` for anchoring.

Each line is a self-contained JSON annotation:

```json
{
  "@context": "http://www.w3.org/ns/anno.jsonld",
  "id": "urn:uuid:...",
  "type": "Annotation",
  "created": "2026-03-12T...",
  "creator": {"type": "Person", "name": "human"},
  "target": {
    "selector": {
      "type": "TextQuoteSelector",
      "exact": "selected text",
      "prefix": "context before ",
      "suffix": " context after"
    }
  },
  "body": [
    {"type": "TextualBody", "value": "Comment text", "creator": {"name": "human"}, "created": "..."},
    {"type": "TextualBody", "value": "Reply text", "creator": {"name": "ai"}, "created": "..."}
  ],
  "scholia:status": "open"
}
```

**Append-only JSONL:** New annotations are appended. Replies append a new version of the full annotation (last-write-wins by `id`). This keeps the file trivially mergeable and human-readable.

**TextQuoteSelector:** Anchors comments to text using exact match + prefix/suffix context, enabling robust re-anchoring after document edits.

## 5. Components

### 5.1 `comments.py` — Data Layer
- `load_comments(doc_path)` → deduplicated list by annotation id (last version wins)
- `append_comment(doc_path, exact, prefix, suffix, body_text, creator)` → new annotation
- `append_reply(doc_path, annotation_id, body_text, creator)` → updated annotation
- `list_open(doc_path)` → annotations with `scholia:status == "open"`

### 5.2 `server.py` — Asyncio Server
- **HTTP GET /** → Pandoc-rendered HTML wrapped in template with injected comments
- **HTTP GET /static/** → serve JS, CSS, vendor assets
- **WebSocket /ws** → bidirectional: push doc/comment updates, receive new comments from browser
- **Watchdog observer** on `.md` and `.scholia.jsonl` → triggers re-render and WS broadcast

### 5.3 Frontend (`template.html` + `scholia.js` + `scholia.css`)
- Dark theme, two-column layout: document + collapsible sidebar
- KaTeX (via Pandoc `--katex`) for math rendering
- Pygments (via Pandoc `--highlight-style`) for code highlighting
- Text selection in document → comment creation form in sidebar
- `dom-anchor-text-quote` (vendored) for TextQuoteSelector ↔ DOM Range conversion
- Highlighted anchor spans in document with hover cross-linking to sidebar cards
- WebSocket client for live updates

### 5.4 `cli.py` — CLI Interface
- `scholia start <doc.md>` — start the server
- `scholia reply <doc> <id> <text>` — reply to an annotation (used by AI)
- `scholia list <doc> [--open]` — list annotations
- `scholia comment <doc> <anchor> <text>` — create a new comment

## 6. Key Design Decisions

| Decision | Rationale |
|----------|-----------|
| Python + Pandoc, no Node | User knows Python; Pandoc handles math/code robustly |
| Vanilla JS, no framework | Minimal deps; sidebar UI is simple enough |
| JSONL, not SQLite | Append-only, human-readable, git-friendly |
| W3C Web Annotation format | Standard data model; TextQuoteSelector is well-specified |
| Vendored anchoring lib | Single small JS file; no npm build step |
| Browser is read-only | Editing happens in user's editor; avoids sync complexity |
| AI uses CLI, not browser | Claude Code runs in terminal; CLI is the natural interface |
| Single aiohttp process | No CORS; simple deployment; one `pip install` |

## 7. Beta Scope (v0.1)

**In scope:**
- Live-rendered markdown with math and code
- Text selection → comment creation in browser sidebar
- Threaded comments with human/AI roles
- CLI for AI to read and reply to comments
- File watcher with WebSocket live reload
- Dark theme UI
- Unread AI reply badges

**Out of scope (future):**
- In-browser reply/edit/delete
- MCP server integration
- Multi-document sessions
- Authentication / multi-user
- Comment resolution / status changes from browser
- Inline annotations (vs. sidebar)

## 8. Verification

```bash
pip install -e .
scholia start brainstormed_plan.md
# → opens browser, renders doc, sidebar works, comments persist
```

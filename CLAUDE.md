# Scholia

Collaborative marginalia for markdown and human-AI dialogue.

## For using scholia (reviewing documents)

See `scholia/data/agent-instructions.md` for the full AI review workflow.
Run `scholia skill-init` to install those instructions as a 'skill' globally or into any project.

## For developing scholia

- Python asyncio server + Pandoc rendering + vanilla JS frontend
- Comments stored in `.scholia.jsonl` (W3C Web Annotation format) and current state in `.scholia.state.json`.
- Tests: `uv run pytest -v`
- Install dev: `uv pip install -e ".[dev]"`

## MCP review loop ("Send to AI")

- `scholia mcp` runs an optional MCP server (`pip install 'scholia[mcp]'`, register with `scholia mcp install`) exposing a `request_review` tool. An agent calls it to **wait in the browser** for the human's review; the human sends comments back with the sidebar's "Send to AI" buttons.
- Architecture: the live review session lives in the `scholia view` server (`scholia/review.py`, `ReviewRegistry`). The MCP process (`scholia/mcp_server.py`) discovers the server via the `_server` state key and long-polls `/api/review/wait`; the browser submits over the WebSocket (`review_submit`). The MCP process never shares memory with the view server — same pattern `scholia mv` uses to reach a running server.
- The rendezvous design is adapted from [md-redline](https://github.com/dejuknow/md-redline) (MIT).

## Configuration

- `SCHOLIA_USERNAME` env var sets creator name in comments (falls back to system username)
- `SCHOLIA_PDF_ENGINE` env var sets the Pandoc PDF engine for export (defaults to `xelatex`, falling back to `lualatex`/`tectonic` if it isn't installed). A Unicode-capable engine is used by default because `pdflatex` errors on common Unicode (e.g. `⇒`). The CLI `--pdf-engine` flag overrides this.
- `pandoc-crossref` (recommended): if installed, scholia automatically uses it as a Pandoc filter, enabling `{#sec:id}` attributes and `@sec:id` cross-references

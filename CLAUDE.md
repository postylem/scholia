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

## Configuration

- `SCHOLIA_USERNAME` env var sets creator name in comments (falls back to system username)
- `pandoc-crossref` (recommended): if installed, scholia automatically uses it as a Pandoc filter, enabling `{#sec:id}` attributes and `@sec:id` cross-references

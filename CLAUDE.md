# Scholia

Collaborative document annotation for human-AI dialogue in markdown margins.

## For using scholia (reviewing documents)

See `scholia/data/agent-instructions.md` for the full AI review workflow.
Run `scholia init` to install these instructions into any project.

## For developing scholia

- Python asyncio server + Pandoc rendering + vanilla JS frontend
- Comments stored in `.scholia.jsonl` (W3C Web Annotation format)
- Tests: `uv run pytest -v`
- Install dev: `uv pip install -e ".[dev]"`

## Configuration

- `SCHOLIA_USERNAME` env var sets creator name in comments (falls back to system username)

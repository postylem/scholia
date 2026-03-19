# CLI Agent-Friendliness Improvements

Improve `scholia list` / `scholia show` output for agent accuracy and token efficiency: short IDs, document-position sort, context window control, cleaner headers.

## Problem

The CLI output was designed for human readability but has several inefficiencies for LLM agents:

- Full `urn:uuid:...` IDs (~50 chars, ~15 tokens each) when agents only need 4-8 character prefixes
- Threads listed in chronological (JSONL-append) order instead of document order, breaking the editorial-pass mental model
- No control over context window size — always 2 lines before/after, regardless of whether the agent wants more or fewer
- Redundant `[open]` status tag on every thread when listing open-only (the default)
- No indication of thread depth (1 message vs 7-message back-and-forth) in the header
- Agent instructions don't recommend `--since` for iterative reviews

## Design

### 1. Short IDs in display output

**Current:** `[open] urn:uuid:a8c086ab-3949-4abe-9679-4e41e05827b8`

**New:** `a8c086ab`

Compute the minimum unique prefix across all annotations in the file (not just displayed ones). Floor of 4 characters. This ensures a given annotation always gets the same short ID regardless of whether `--all` is active.

**New helper in `comments.py`:**

```python
def short_id_map(doc_path: str | Path) -> dict[str, str]:
    """Map full annotation IDs to minimum unique prefixes (floor 4 chars).

    Computes against ALL annotations in the file for stable results
    regardless of display filters.
    """
```

**Callers:** `cmd_list` and `cmd_show` call `short_id_map()` once, then pass the short ID to `_print_annotation`. The full-ID header line `print(f"[{status}] {ann['id']}")` becomes `print(f"{short_id}")` (or with status/message-count, see below).

### 2. Sort anchored threads by document position

**Current:** `cmd_list` separates anchored vs orphaned threads, but anchored threads retain JSONL-append order.

**New:** Sort anchored threads ascending by `ctx['line']`. Orphans remain at the end in existing order.

**Implementation:** `cmd_list` already calls `locate_anchor()` to classify threads. Store the ctx result alongside the annotation to avoid the double-lookup (fixing the existing TODO on line 318-319 of `cli.py`). Sort anchored list by `ctx['line']` before printing.

```python
# In cmd_list, replace the current anchored/orphaned classification:
anchored = []  # list of (annotation, ctx)
orphaned = []
for ann in items:
    selector = ann.get("target", {}).get("selector", {})
    ctx = locate_anchor(args.doc, selector)
    if ctx["found"]:
        anchored.append((ann, ctx))
    else:
        orphaned.append(ann)

anchored.sort(key=lambda pair: pair[1]["line"])

for ann, ctx in anchored:
    _print_annotation(ann, fmt=args.fmt, doc_path=args.doc, ctx=ctx, ...)
```

`_print_annotation` accepts an optional pre-computed `ctx` to avoid re-calling `locate_anchor`.

### 3. `--context N M` flag

**Current:** Context window hardcoded to 2 lines before, 2 after in `context.py:159-161`.

**New:** `--context N M` argument on `list` and `show` subparsers. `N` = lines before anchor, `M` = lines after. Default `2 2`.

**CLI parsing:** `nargs=2, type=int, default=[2, 2], metavar=('BEFORE', 'AFTER')`

**`locate_anchor()` signature change:**

```python
def locate_anchor(doc_path, selector, *, context_before=2, context_after=2) -> dict:
```

Lines 159-161 of `context.py` change from:

```python
ctx_start = max(0, anchor_line - 2)
ctx_end = min(len(lines), anchor_line + exact_line_count + 2)
```

to:

```python
ctx_start = max(0, anchor_line - context_before)
ctx_end = min(len(lines), anchor_line + exact_line_count + context_after)
```

**Only affects `context` format.** Silently ignored for `messages-only`, `summary`, `raw`.

### 4. Drop redundant `[open]` on default listing

**Current:** `[open] urn:uuid:a8c086ab-...` on every thread.

**New:**
- `scholia list doc.md` (open-only) → no status tag
- `scholia list doc.md --all` → `[open]` / `[resolved]` prefix
- `scholia show doc.md <id>` → always shows status (single-thread view, status is useful context)

**Implementation:** `_print_annotation` gets a `show_status: bool` parameter. `cmd_list` passes `show_status=args.all`. `cmd_show` passes `show_status=True`.

### 5. Message count in header

**Current header:** `[open] urn:uuid:a8c086ab-...`

**New header examples:**
- Fresh comment (1 message): `a8c086ab`
- Thread with replies: `a8c086ab (3 messages)`

Count shown only when `len(bodies) > 1`. Single-message threads get no count — a lone comment is self-evident.

### 6. Update `agent-instructions.md`

**a. `--since` for iterative reviews.** Add to the workflow section:

> For follow-up reviews (when you've already reviewed this document before), use `scholia list <doc.md> --since <ISO-timestamp>` to see only threads with activity since your last pass. Record the current time before listing so you can use it next time.

**b. `--context N M` documentation.** Add to the CLI reference, with guidance that the default is fine for most cases. Agents can tighten to `1 1` for large documents with many threads, or widen for dense passages.

**c. Update the example session.** Run the actual CLI against a test fixture after all changes are implemented and paste the real output. Do not hand-craft the example.

## Files changed

| File | Changes |
|------|---------|
| `scholia/comments.py` | Add `short_id_map()` helper |
| `scholia/context.py` | Add `context_before`/`context_after` params to `locate_anchor()` |
| `scholia/cli.py` | Short IDs, doc-position sort, `--context` flag, `show_status` param, message count, pass pre-computed ctx |
| `scholia/data/agent-instructions.md` | `--since` guidance, `--context` docs, updated example from real CLI output |
| `tests/test_core.py` | Update expected output for new format; test short ID computation, sorting, context window sizes |

## Out of scope

- Agent attention-tracking / "updated" dirty bit (use `--since` instead)
- Frontend refactoring (separate initiative, rationale documented)
- New output formats (existing four formats are sufficient)

"""Locate annotation anchors within a markdown document and extract context."""

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path


def _find_all_occurrences(text: str, exact: str) -> list[int]:
    """Find all character offsets where *exact* appears in *text*."""
    candidates: list[int] = []
    start = 0
    while True:
        idx = text.find(exact, start)
        if idx == -1:
            break
        candidates.append(idx)
        start = idx + 1
    return candidates


def _score_candidate(text: str, idx: int, exact: str, prefix: str, suffix: str) -> int:
    """Score a single candidate by prefix/suffix character overlap.

    Mirrors the browser's ``toRange()`` logic: count consecutive matching
    characters from the boundary between context and exact text.
    """
    score = 0
    if prefix:
        before = text[max(0, idx - len(prefix)):idx]
        for i in range(min(len(before), len(prefix))):
            if before[len(before) - 1 - i] == prefix[len(prefix) - 1 - i]:
                score += 1
            else:
                break
    if suffix:
        after = text[idx + len(exact):idx + len(exact) + len(suffix)]
        for i in range(min(len(after), len(suffix))):
            if after[i] == suffix[i]:
                score += 1
            else:
                break
    return score


def _best_by_scoring(text: str, candidates: list[int], exact: str,
                     prefix: str, suffix: str) -> tuple[int, bool]:
    """Pick the best candidate using prefix/suffix scoring.

    Returns ``(char_offset, is_decisive)`` where *is_decisive* is True when
    the winner's score is strictly greater than the runner-up's.
    """
    best_idx = candidates[0]
    best_score = -1
    second_best = -1
    for idx in candidates:
        s = _score_candidate(text, idx, exact, prefix, suffix)
        if s > best_score:
            second_best = best_score
            best_score = s
            best_idx = idx
        elif s > second_best:
            second_best = s
    return best_idx, (best_score > second_best)


def render_doc_plain(doc_path: str | Path) -> str | None:
    """Render a document to plain text via Pandoc for anchor resolution.

    Returns the plain-text rendering, or None if Pandoc is unavailable.
    """
    if not shutil.which("pandoc"):
        return None
    try:
        result = subprocess.run(
            ["pandoc", "-t", "plain", "--wrap=none", str(doc_path)],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0:
            return result.stdout
    except (subprocess.TimeoutExpired, OSError):
        pass
    return None


def _find_anchor_pos(full_text: str, selector: dict,
                     rendered_text: str | None = None) -> int | None:
    """Find the character offset where the exact anchor text starts.

    Uses prefix/suffix scoring (like the browser's ``toRange()``) to
    disambiguate when the exact text appears multiple times.  When
    *rendered_text* is supplied (Pandoc plain-text rendering of the
    document), it is also scored — this handles annotations whose
    prefix/suffix were captured from the browser's rendered DOM.

    Returns a character offset into *full_text*, or None if not found.
    """
    exact = selector.get("exact", "")
    prefix = selector.get("prefix", "")
    suffix = selector.get("suffix", "")
    if not exact:
        return None

    raw_candidates = _find_all_occurrences(full_text, exact)
    if not raw_candidates:
        return None
    if len(raw_candidates) == 1:
        return raw_candidates[0]

    # Multiple occurrences — disambiguate via prefix/suffix scoring.
    if not prefix and not suffix:
        return raw_candidates[0]

    raw_best, raw_decisive = _best_by_scoring(
        full_text, raw_candidates, exact, prefix, suffix)

    if raw_decisive:
        return raw_best

    # Raw scoring was ambiguous.  Try rendered text (closer to browser DOM).
    if rendered_text is not None:
        rendered_candidates = _find_all_occurrences(rendered_text, exact)
        if rendered_candidates:
            rendered_best, rendered_decisive = _best_by_scoring(
                rendered_text, rendered_candidates, exact, prefix, suffix)
            if rendered_decisive:
                # Map rendered occurrence index back to raw text.
                occurrence = rendered_candidates.index(rendered_best)
                if occurrence < len(raw_candidates):
                    return raw_candidates[occurrence]

    # Fallback: best raw score (or first occurrence if all tied at 0).
    return raw_best


def _heading_breadcrumb(lines: list[str], anchor_line: int) -> tuple[str | None, int | None]:
    """Build a breadcrumb like '§ Chapter > Section > Subsection'.

    Returns (breadcrumb_string, line_number_of_nearest_heading) where
    line_number is 0-based, or (None, None) if no heading found.
    """
    headings: list[tuple[int, int, str]] = []  # (level, line_idx, text)
    for i in range(anchor_line + 1):
        m = re.match(r"^(#{1,6})\s+(.+)", lines[i])
        if m:
            level = len(m.group(1))
            text = m.group(2).strip()
            while headings and headings[-1][0] >= level:
                headings.pop()
            headings.append((level, i, text))

    if not headings:
        return None, None
    nearest_line = headings[-1][1]
    breadcrumb = "§ " + " > ".join(h[2] for h in headings)
    return breadcrumb, nearest_line


def _use_color() -> bool:
    """Check if stderr/stdout supports color."""
    if os.environ.get("NO_COLOR"):
        return False
    if os.environ.get("FORCE_COLOR"):
        return True
    return hasattr(sys.stdout, "isatty") and sys.stdout.isatty()


# ANSI escape helpers
_BOLD = "\033[1m"
_UNDERLINE = "\033[4m"
_YELLOW = "\033[33m"
_DIM = "\033[2m"
_RESET = "\033[0m"


def _fmt_gutter_line(
    gutter: str, text: str, highlight: tuple[int, int] | None, color: bool,
) -> list[str]:
    """Format a single gutter line, optionally highlighting a span.

    Returns a list of 1 or 2 strings (line + optional caret line).
    gutter is the left-side label (line number or spaces).
    highlight is (col_start, col_end) within text, or None for a plain context line.
    """
    lines = []
    if highlight:
        col_s, col_e = highlight
        before = text[:col_s]
        selected = text[col_s:col_e]
        after = text[col_e:]
        if color:
            lines.append(f"  {_DIM}{gutter} |  {before}{_RESET}"
                         f"{_BOLD}{_YELLOW}{selected}{_RESET}"
                         f"{_DIM}{after}{_RESET}")
            lines.append(f"  {_DIM}{' ' * len(gutter)} |  {_RESET}"
                         f"{' ' * col_s}{_YELLOW}{'^' * max(1, col_e - col_s)}{_RESET}")
        else:
            lines.append(f"  {gutter} |  {text}")
            lines.append(f"  {' ' * len(gutter)} |  {' ' * col_s}{'^' * max(1, col_e - col_s)}")
    else:
        if color:
            lines.append(f"  {_DIM}{gutter} |  {text}{_RESET}")
        else:
            lines.append(f"  {gutter} |  {text}")
    return lines


def format_orphan_context(selector: dict) -> list[str]:
    """Format the stored prefix/exact/suffix from an orphaned annotation.

    Returns formatted lines in the same gutter style as live context.
    """
    exact = selector.get("exact", "")
    prefix = selector.get("prefix", "")
    suffix = selector.get("suffix", "")

    exact_flat = exact.replace("\n", " ")
    before = ("..." + prefix.replace("\n", " ")) if prefix else ""
    after = (suffix.replace("\n", " ") + "...") if suffix else ""
    full_line = f"{before}{exact_flat}{after}"
    col_s = len(before)
    col_e = col_s + len(exact_flat)

    color = _use_color()
    gutter = " " * 3  # no line numbers for orphans
    return _fmt_gutter_line(gutter, full_line, (col_s, col_e), color)


def locate_anchor(doc_path: str | Path, selector: dict, *,
                  context_before: int = 2, context_after: int = 2,
                  rendered_text: str | None = ...) -> dict:
    """Find an annotation's anchor in the document and return context.

    *rendered_text* is an optional Pandoc plain-text rendering of the
    document used for better anchor disambiguation.  Pass ``None`` to
    skip rendered-text scoring; omit (or pass the sentinel ``...``) to
    have it computed automatically via :func:`render_doc_plain`.

    Returns a dict with:
        found: bool
        line: int | None (1-based line where anchor starts)
        heading: str | None (breadcrumb like '§ Section > Subsection')
        context_lines: list[str] | None (formatted lines with line numbers and markers)
    """
    path = Path(doc_path).resolve()
    if not path.exists():
        return {"found": False, "line": None, "heading": None, "context_lines": None}

    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    exact = selector.get("exact", "")

    if rendered_text is ...:
        rendered_text = render_doc_plain(path)

    char_pos = _find_anchor_pos(text, selector, rendered_text=rendered_text)
    if char_pos is None:
        return {"found": False, "line": None, "heading": None, "context_lines": None}

    # Map char_pos to line/col
    anchor_line = text[:char_pos].count("\n")
    line_start = text.rfind("\n", 0, char_pos) + 1  # char offset of anchor_line start
    anchor_col = char_pos - line_start  # 0-based column in that line

    heading, heading_line = _heading_breadcrumb(lines, anchor_line)

    # How many lines does the exact text span?
    exact_end = char_pos + len(exact)
    end_line = text[:exact_end].count("\n")
    exact_line_count = end_line - anchor_line + 1

    # Context window: configurable lines before/after anchor
    ctx_start = max(0, anchor_line - context_before)
    ctx_end = min(len(lines), anchor_line + exact_line_count + context_after)

    # Line number gutter width
    max_lineno = ctx_end
    gutter_w = len(str(max_lineno))

    color = _use_color()

    # Build the exact text positions per line
    # For each line in the anchor range, compute (col_start, col_end) of the selection
    anchor_spans: dict[int, tuple[int, int]] = {}
    remaining = exact
    for li in range(anchor_line, anchor_line + exact_line_count):
        line_content = lines[li] if li < len(lines) else ""
        if li == anchor_line:
            col_s = anchor_col
        else:
            col_s = 0

        # How much of 'remaining' fits on this line?
        avail = len(line_content) - col_s
        if li < anchor_line + exact_line_count - 1:
            # This line is fully covered; remaining continues after newline
            col_e = len(line_content)
            consumed = avail + 1  # +1 for the newline
        else:
            # Last line of anchor
            col_e = col_s + len(remaining)
            consumed = len(remaining)

        anchor_spans[li] = (col_s, min(col_e, len(line_content)))
        remaining = remaining[consumed:]

    formatted: list[str] = []
    for i in range(ctx_start, ctx_end):
        lineno = str(i + 1).rjust(gutter_w)
        line_content = lines[i] if i < len(lines) else ""
        highlight = anchor_spans.get(i)
        formatted.extend(_fmt_gutter_line(lineno, line_content, highlight, color))

    # Add skip indicator if heading exists and isn't adjacent to context
    if heading and heading_line is not None and heading_line < ctx_start:
        skip_line = f"  {' ' * gutter_w}    ..."
        if color:
            skip_line = f"  {_DIM}{' ' * gutter_w}    ...{_RESET}"
        formatted.insert(0, skip_line)

    # End column: find where exact text ends
    end_line = text[:char_pos + len(exact)].count("\n")
    end_line_start = text.rfind("\n", 0, char_pos + len(exact)) + 1
    end_col = char_pos + len(exact) - end_line_start

    return {
        "found": True,
        "line": anchor_line + 1,
        "col": anchor_col + 1,         # 1-based
        "end_line": end_line + 1,       # 1-based
        "end_col": end_col + 1,         # 1-based, exclusive
        "heading": heading,
        "heading_line": (heading_line + 1) if heading_line is not None else None,
        "context_lines": formatted,
    }

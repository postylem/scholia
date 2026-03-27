/**
 * Minimal TextQuoteSelector anchoring (W3C Web Annotation compatible).
 * Converts between TextQuoteSelector objects and DOM Ranges.
 *
 * Inspired by the dom-anchor-text-quote package from the Hypothesis project.
 * Self-contained — no dependencies.
 */
(function (global) {
  'use strict';

  /**
   * Score a candidate occurrence by consecutive prefix/suffix character overlap.
   * Counts backward through prefix and forward through suffix, stopping at
   * first mismatch. Used by both fromRange (ambiguity check) and toRange.
   */
  function _scoreCandidate(text, idx, exact, prefix, suffix) {
    var score = 0;
    if (prefix) {
      var before = text.slice(Math.max(0, idx - prefix.length), idx);
      for (var i = 0; i < Math.min(before.length, prefix.length); i++) {
        if (before[before.length - 1 - i] === prefix[prefix.length - 1 - i]) {
          score++;
        } else {
          break;
        }
      }
    }
    if (suffix) {
      var after = text.slice(idx + exact.length, idx + exact.length + suffix.length);
      for (var i = 0; i < Math.min(after.length, suffix.length); i++) {
        if (after[i] === suffix[i]) {
          score++;
        } else {
          break;
        }
      }
    }
    return score;
  }

  /**
   * Check whether prefix/suffix context uniquely identifies the occurrence
   * at correctIdx among all occurrences of exact in text.
   */
  function _isDisambiguated(text, exact, correctIdx, prefix, suffix) {
    var searchStart = 0;
    var bestScore = -1, bestIdx = -1, secondBest = -1;
    while (true) {
      var idx = text.indexOf(exact, searchStart);
      if (idx === -1) break;
      var score = _scoreCandidate(text, idx, exact, prefix, suffix);
      if (score > bestScore) {
        secondBest = bestScore;
        bestScore = score;
        bestIdx = idx;
      } else if (score > secondBest) {
        secondBest = score;
      }
      searchStart = idx + 1;
    }
    return bestIdx === correctIdx && bestScore > secondBest;
  }

  /**
   * Build a TextQuoteSelector with adaptive context.
   * Starts with a small window and widens until the prefix/suffix
   * unambiguously identify this occurrence (or hits a ceiling).
   */
  function _selectorWithAdaptiveContext(text, start, end) {
    var selected = text.slice(start, end);
    var MIN_CONTEXT = 32;
    var MAX_CONTEXT = 1024;
    var context = MIN_CONTEXT;

    // Quick check: is exact text unique?
    var firstIdx = text.indexOf(selected);
    var isUnique = (firstIdx === -1 || text.indexOf(selected, firstIdx + 1) === -1);

    if (!isUnique) {
      while (context < MAX_CONTEXT) {
        var p = text.slice(Math.max(0, start - context), start);
        var s = text.slice(end, Math.min(text.length, end + context));
        if (_isDisambiguated(text, selected, start, p, s)) break;
        context *= 2;
      }
    }

    return {
      type: 'TextQuoteSelector',
      exact: selected,
      prefix: text.slice(Math.max(0, start - context), start),
      suffix: text.slice(end, Math.min(text.length, end + context)),
    };
  }

  /**
   * Create a TextQuoteSelector from a DOM Range.
   * Captures the selected text plus prefix/suffix context for re-anchoring.
   * Context window widens automatically when exact text is ambiguous.
   */
  function fromRange(root, range) {
    var text = root.textContent || '';
    var selected = range.toString();

    // Walk to find the text offset of the range start
    var preRange = document.createRange();
    preRange.setStart(root, 0);
    preRange.setEnd(range.startContainer, range.startOffset);
    var start = preRange.toString().length;

    return _selectorWithAdaptiveContext(text, start, start + selected.length);
  }

  /**
   * Find a DOM Range from a TextQuoteSelector.
   * Searches for exact text, scores candidates by prefix/suffix overlap.
   */
  function toRange(root, selector) {
    var text = root.textContent || '';
    var exact = selector.exact;
    var prefix = selector.prefix || '';
    var suffix = selector.suffix || '';

    if (!exact) return null;

    // Find all occurrences of exact text
    var candidates = [];
    var searchStart = 0;
    while (true) {
      var idx = text.indexOf(exact, searchStart);
      if (idx === -1) break;
      candidates.push(idx);
      searchStart = idx + 1;
    }

    if (candidates.length === 0) return null;

    var bestIdx = candidates[0];
    var bestScore = -1;

    for (var c = 0; c < candidates.length; c++) {
      var score = _scoreCandidate(text, candidates[c], exact, prefix, suffix);
      if (score > bestScore) {
        bestScore = score;
        bestIdx = candidates[c];
      }
    }

    return textOffsetToRange(root, bestIdx, bestIdx + exact.length);
  }

  /**
   * Convert text character offsets to a DOM Range.
   */
  function textOffsetToRange(root, start, end) {
    var walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    var offset = 0;
    var startNode = null, startOffset = 0;
    var endNode = null, endOffset = 0;

    while (walker.nextNode()) {
      var node = walker.currentNode;
      var len = node.textContent.length;

      if (!startNode && offset + len > start) {
        startNode = node;
        startOffset = start - offset;
      }
      if (offset + len >= end) {
        endNode = node;
        endOffset = end - offset;
        break;
      }
      offset += len;
    }

    if (!startNode || !endNode) return null;

    var range = document.createRange();
    range.setStart(startNode, startOffset);
    range.setEnd(endNode, endOffset);
    return range;
  }

  function buildRecoverableMap(root) {
    var text = '';
    var entries = [];

    function isInsideKatex(node) {
      var el = node.nodeType === Node.TEXT_NODE ? node.parentElement : node;
      return el && el.closest && el.closest('.katex');
    }

    function walk(node) {
      if (node.nodeType === Node.TEXT_NODE) {
        if (isInsideKatex(node)) return;
        entries.push({ node: node, rtStart: text.length, type: 'text' });
        text += node.textContent;
        entries[entries.length - 1].rtEnd = text.length;
        return;
      }
      if (node.nodeType !== Node.ELEMENT_NODE) return;

      // Math span (Pandoc outputs <span class="math inline"> or <span class="math display">)
      // After KaTeX renders, data-latex holds the original LaTeX source
      if (node.classList.contains('math') && node.dataset.latex) {
        var d = node.classList.contains('display') ? '$$' : '$';
        entries.push({ node: node, rtStart: text.length, type: 'math' });
        text += d + node.dataset.latex + d;
        entries[entries.length - 1].rtEnd = text.length;
        return;
      }

      // Fallback: .math span with KaTeX annotation element (no data-latex)
      if (node.classList.contains('math') && node.querySelector('.katex')) {
        var ann = node.querySelector('annotation[encoding="application/x-tex"]');
        if (ann) {
          var d2 = node.classList.contains('display') ? '$$' : '$';
          entries.push({ node: node, rtStart: text.length, type: 'math' });
          text += d2 + ann.textContent + d2;
          entries[entries.length - 1].rtEnd = text.length;
          return;
        }
      }

      // Skip nodes inside .katex (handled by the .math parent above)
      if (isInsideKatex(node)) return;

      // Citation spans: <span class="citation" data-cites="key">(...)</span>
      // Parenthetical citations start with "(" → source is [@key]
      // Narrative citations (e.g., "Turing (1936)") → source is @key
      if (node.classList && node.classList.contains('citation') && node.dataset.cites) {
        var citeKey = node.dataset.cites;
        var isParenthetical = (node.textContent || '').trimStart().charAt(0) === '(';
        var citeText = isParenthetical ? '[@' + citeKey + ']' : '@' + citeKey;
        entries.push({ node: node, rtStart: text.length, type: 'cite' });
        text += citeText;
        entries[entries.length - 1].rtEnd = text.length;
        return;
      }

      // Crossref links: pandoc-crossref outputs <a href="#sec:id">sec. 1</a> etc
      if (node.tagName === 'A') {
        var href = node.getAttribute('href') || '';
        var crMatch = href.match(/^#((?:sec|eq|fig|tbl|lst):.+)/);
        if (crMatch) {
          // Trim pandoc-crossref display prefix from preceding text
          // e.g., "eq.\xa0", "§\xa0", "fig.\xa0" etc.
          if (entries.length > 0 && entries[entries.length - 1].type === 'text') {
            var prev = entries[entries.length - 1];
            var prevText = text.slice(prev.rtStart);
            var trimmed = prevText.replace(/(?:§|sec\.|eq\.|fig\.|tbl\.|lst\.)[\s\xa0]*$/, '');
            if (trimmed.length < prevText.length) {
              text = text.slice(0, prev.rtStart) + trimmed;
              prev.rtEnd = text.length;
            }
          }
          entries.push({ node: node, rtStart: text.length, type: 'ref' });
          text += '@' + crMatch[1];
          entries[entries.length - 1].rtEnd = text.length;
          return;
        }
      }

      for (var i = 0; i < node.childNodes.length; i++) {
        walk(node.childNodes[i]);
      }
    }

    walk(root);
    return { text: text, entries: entries };
  }

  function domToRT(entries, container, offset) {
    var i;
    // Text node: find matching entry
    if (container.nodeType === Node.TEXT_NODE) {
      for (i = 0; i < entries.length; i++) {
        if (entries[i].node === container && entries[i].type === 'text') {
          return entries[i].rtStart + Math.min(offset, container.textContent.length);
        }
      }
    }

    // Element node: offset is a child index
    if (container.nodeType === Node.ELEMENT_NODE) {
      var targetChild = container.childNodes[offset];
      if (targetChild) {
        for (i = 0; i < entries.length; i++) {
          var eNode = entries[i].node;
          if (eNode === targetChild || targetChild.contains(eNode)) {
            return entries[i].rtStart;
          }
        }
      }
      // Past end of children: last entry inside container
      for (i = entries.length - 1; i >= 0; i--) {
        if (container.contains(entries[i].node)) {
          return entries[i].rtEnd;
        }
      }
    }

    // Fallback: container is inside a special entry (math, ref, cite)
    // that swallowed its children during the walk. Snap to entry boundary.
    var el = container.nodeType === Node.TEXT_NODE ? container.parentElement : container;
    if (el) {
      for (i = 0; i < entries.length; i++) {
        if (entries[i].type !== 'text' && entries[i].node.contains(el)) {
          return entries[i].rtEnd;
        }
      }
    }

    return 0;
  }

  /**
   * Find the nearest "atomic" element that shouldn't be partially selected:
   * math expressions, crossref links, or citation links.
   */
  function _closestAtomicElement(el) {
    if (!el || !el.closest) return null;
    var math = el.closest('span.math');
    if (math) return math;
    var citation = el.closest('span.citation');
    if (citation) return citation;
    var link = el.closest('a');
    if (link) {
      var href = link.getAttribute('href') || '';
      if (/^#(?:(?:sec|eq|fig|tbl|lst):|ref-)/.test(href)) return link;
    }
    return null;
  }

  /**
   * Snap a range so it doesn't start or end inside a math expression,
   * crossref link, or citation link. Returns a new (cloned) Range.
   */
  function snapToMathBoundaries(range) {
    var newRange = range.cloneRange();

    var startEl = range.startContainer.nodeType === Node.TEXT_NODE
      ? range.startContainer.parentElement : range.startContainer;
    var startAtomic = _closestAtomicElement(startEl);
    if (startAtomic) {
      newRange.setStartBefore(startAtomic);
    }

    var endEl = range.endContainer.nodeType === Node.TEXT_NODE
      ? range.endContainer.parentElement : range.endContainer;
    var endAtomic = _closestAtomicElement(endEl);
    if (endAtomic) {
      newRange.setEndAfter(endAtomic);
    }

    return newRange;
  }

  function fromRangeRecoverable(root, range) {
    var snapped = snapToMathBoundaries(range);
    var map = buildRecoverableMap(root);
    var text = map.text;

    var start = domToRT(map.entries, snapped.startContainer, snapped.startOffset);
    var end = domToRT(map.entries, snapped.endContainer, snapped.endOffset);

    if (start > end) { var tmp = start; start = end; end = tmp; }
    if (start === end) return null;

    return _selectorWithAdaptiveContext(text, start, end);
  }

  /**
   * Convert recoverable-text character offsets back to a DOM Range.
   * Inverse of domToRT — maps positions in the recoverable text space
   * back to positions in the actual DOM tree.
   */
  function rtToRange(entries, rtStart, rtEnd) {
    var startNode = null, startOffset = 0;
    var endNode = null, endOffset = 0;

    for (var i = 0; i < entries.length; i++) {
      var e = entries[i];

      if (!startNode && e.rtEnd > rtStart) {
        if (e.type === 'text') {
          startNode = e.node;
          startOffset = rtStart - e.rtStart;
        } else {
          // Math/ref/cite element: position before it
          startNode = e.node.parentNode;
          startOffset = Array.prototype.indexOf.call(startNode.childNodes, e.node);
        }
      }

      if (e.rtEnd >= rtEnd) {
        if (e.type === 'text' && rtEnd > e.rtStart) {
          endNode = e.node;
          endOffset = rtEnd - e.rtStart;
        } else if (e.type !== 'text') {
          // Math/ref/cite element: position after it
          endNode = e.node.parentNode;
          endOffset = Array.prototype.indexOf.call(endNode.childNodes, e.node) + 1;
        } else {
          // rtEnd falls at or before this text node's start
          endNode = e.node;
          endOffset = 0;
        }
        break;
      }
    }

    if (!startNode || !endNode) return null;

    var range = document.createRange();
    range.setStart(startNode, startOffset);
    range.setEnd(endNode, endOffset);
    return range;
  }

  /**
   * Find a DOM Range from a source-space TextQuoteSelector.
   * Searches in recoverable text (LaTeX for math, @ref for crossrefs)
   * and maps the match back to DOM positions.
   */
  function toRangeRecoverable(root, selector) {
    var map = buildRecoverableMap(root);
    var text = map.text;
    var exact = selector.exact;
    var prefix = selector.prefix || '';
    var suffix = selector.suffix || '';

    if (!exact) return null;

    var candidates = [];
    var searchStart = 0;
    while (true) {
      var idx = text.indexOf(exact, searchStart);
      if (idx === -1) break;
      candidates.push(idx);
      searchStart = idx + 1;
    }

    if (candidates.length === 0) return null;

    var bestIdx = candidates[0];
    var bestScore = -1;

    for (var c = 0; c < candidates.length; c++) {
      var score = _scoreCandidate(text, candidates[c], exact, prefix, suffix);
      if (score > bestScore) {
        bestScore = score;
        bestIdx = candidates[c];
      }
    }

    return rtToRange(map.entries, bestIdx, bestIdx + exact.length);
  }

  global.TextQuoteAnchor = {
    fromRange: fromRange,
    fromRangeRecoverable: fromRangeRecoverable,
    snapToMathBoundaries: snapToMathBoundaries,
    toRange: toRange,
    toRangeRecoverable: toRangeRecoverable
  };
})(window);

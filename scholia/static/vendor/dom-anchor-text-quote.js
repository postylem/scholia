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
   * Create a TextQuoteSelector from a DOM Range.
   * Captures the selected text plus prefix/suffix context for re-anchoring.
   */
  function fromRange(root, range) {
    var text = root.textContent || '';
    var selected = range.toString();

    // Walk to find the text offset of the range start
    var preRange = document.createRange();
    preRange.setStart(root, 0);
    preRange.setEnd(range.startContainer, range.startOffset);
    var start = preRange.toString().length;

    var CONTEXT = 32;
    var prefixStart = Math.max(0, start - CONTEXT);
    var suffixEnd = Math.min(text.length, start + selected.length + CONTEXT);

    return {
      type: 'TextQuoteSelector',
      exact: selected,
      prefix: text.slice(prefixStart, start),
      suffix: text.slice(start + selected.length, suffixEnd),
    };
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

    // Score candidates by prefix/suffix context match
    var bestIdx = candidates[0];
    var bestScore = -1;

    for (var c = 0; c < candidates.length; c++) {
      var idx = candidates[c];
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

      if (score > bestScore) {
        bestScore = score;
        bestIdx = idx;
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

  global.TextQuoteAnchor = { fromRange: fromRange, toRange: toRange };
})(window);

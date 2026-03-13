/**
 * Scholia frontend v0.2: sidebar, text selection, WebSocket live reload,
 * anchor highlighting, read/unread state, reply, resolve, code chrome,
 * positioned cards with orphan handling.
 */
(function () {
  'use strict';

  var ws;
  var comments = window.__SCHOLIA_COMMENTS__ || [];
  var state = window.__SCHOLIA_STATE__ || {};
  var docEl = document.getElementById('scholia-doc');
  var sidebarEl = document.getElementById('scholia-sidebar');
  var highlights = new Map();   // annotation id → [mark elements]
  var orphanIds = new Set();
  var filterMode = 'open';      // 'open' or 'all'

  // ── WebSocket ──────────────────────────────────────

  function connectWS() {
    var proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
    ws = new WebSocket(proto + '//' + location.host + '/ws');

    ws.onmessage = function (e) {
      var msg = JSON.parse(e.data);
      if (msg.type === 'doc_update') {
        docEl.innerHTML = msg.html;
        rerenderMath();
        decorateCodeBlocks();
        reanchorAll();
        positionCards();
      } else if (msg.type === 'comments_update') {
        comments = msg.comments;
        renderSidebar();
        reanchorAll();
        positionCards();
      } else if (msg.type === 'error') {
        console.warn('Scholia server error:', msg.message);
      }
    };

    ws.onclose = function () {
      setTimeout(connectWS, 2000);
    };
  }

  function wsSend(obj) {
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify(obj));
    }
  }

  // ── Math rendering ─────────────────────────────────

  function rerenderMath() {
    if (!window.katex) return;
    // Pandoc --katex outputs <span class="math inline"> and <span class="math display">
    var mathEls = docEl.querySelectorAll('span.math');
    for (var i = 0; i < mathEls.length; i++) {
      var el = mathEls[i];
      var displayMode = el.classList.contains('display');
      try {
        katex.render(el.textContent, el, { displayMode: displayMode, throwOnError: false });
      } catch (e) {
        // leave raw LaTeX visible on error
      }
    }
  }

  // ── Code block chrome ──────────────────────────────

  function decorateCodeBlocks() {
    var blocks = docEl.querySelectorAll('div.sourceCode');
    for (var i = 0; i < blocks.length; i++) {
      var div = blocks[i];
      // Skip if already decorated
      if (div.querySelector('.scholia-code-lang') || div.querySelector('.scholia-code-copy')) continue;

      var pre = div.querySelector('pre');
      if (!pre) continue;

      // Detect language from pre's classList: skip 'sourceCode', take the other
      var lang = '';
      for (var c = 0; c < pre.classList.length; c++) {
        if (pre.classList[c] !== 'sourceCode') {
          lang = pre.classList[c];
          break;
        }
      }

      if (lang) {
        var langSpan = document.createElement('span');
        langSpan.className = 'scholia-code-lang';
        langSpan.textContent = lang.charAt(0).toUpperCase() + lang.slice(1);
        div.appendChild(langSpan);
      }

      var copyBtn = document.createElement('button');
      copyBtn.className = 'scholia-code-copy';
      copyBtn.textContent = 'Copy';
      copyBtn.addEventListener('click', (function (theDiv, theBtn) {
        return function () {
          var codeEl = theDiv.querySelector('code');
          if (!codeEl) return;
          navigator.clipboard.writeText(codeEl.textContent).then(function () {
            theBtn.textContent = 'Copied!';
            setTimeout(function () { theBtn.textContent = 'Copy'; }, 1500);
          });
        };
      })(div, copyBtn));
      div.appendChild(copyBtn);
    }
  }

  // ── Unread detection ───────────────────────────────

  function isUnread(ann) {
    var annState = state[ann.id];
    var lastReadAt = annState && annState.lastReadAt;
    if (!lastReadAt) return true;

    var lastReadDate = new Date(lastReadAt);
    var bodies = ann.body || [];
    for (var i = 0; i < bodies.length; i++) {
      if (bodies[i].created && new Date(bodies[i].created) > lastReadDate) {
        return true;
      }
    }
    return false;
  }

  // ── Sidebar ────────────────────────────────────────

  function renderSidebar() {
    // Preserve any open new-comment form
    var existingForm = document.getElementById('scholia-new-comment');

    sidebarEl.innerHTML = '';

    if (existingForm) {
      sidebarEl.appendChild(existingForm);
    }

    // Filter controls
    var controls = document.createElement('div');
    controls.className = 'scholia-sidebar-controls';

    var openBtn = document.createElement('button');
    openBtn.className = 'scholia-filter-btn' + (filterMode === 'open' ? ' active' : '');
    openBtn.textContent = 'Open';
    openBtn.addEventListener('click', function () {
      filterMode = 'open';
      renderSidebar();
      positionCards();
    });
    controls.appendChild(openBtn);

    var allBtn = document.createElement('button');
    allBtn.className = 'scholia-filter-btn' + (filterMode === 'all' ? ' active' : '');
    allBtn.textContent = 'All';
    allBtn.addEventListener('click', function () {
      filterMode = 'all';
      renderSidebar();
      positionCards();
    });
    controls.appendChild(allBtn);

    sidebarEl.appendChild(controls);

    // Filter comments
    var filtered = [];
    for (var i = 0; i < comments.length; i++) {
      var ann = comments[i];
      var status = ann['scholia:status'] || 'open';
      if (filterMode === 'open' && status !== 'open') continue;
      filtered.push(ann);
    }

    if (filtered.length === 0) {
      var empty = document.createElement('div');
      empty.className = 'scholia-empty';
      empty.textContent = filterMode === 'open'
        ? 'No open comments. Select text to add one.'
        : 'No comments yet. Select text to add one.';
      sidebarEl.appendChild(empty);
      return;
    }

    for (var j = 0; j < filtered.length; j++) {
      sidebarEl.appendChild(createCard(filtered[j]));
    }
  }

  function createCard(ann) {
    var card = document.createElement('div');
    card.className = 'scholia-card';
    card.dataset.annotationId = ann.id;

    var status = ann['scholia:status'] || 'open';
    if (status === 'open') card.classList.add('scholia-open');
    if (status === 'resolved') card.classList.add('scholia-resolved');

    // Orphan detection
    if (orphanIds.has(ann.id)) {
      card.classList.add('scholia-orphan');
    }

    // Unread detection (timestamp-based)
    var unread = isUnread(ann);
    if (unread) card.classList.add('scholia-unread');

    // Determine unread badge text
    var bodies = ann.body || [];
    var badgeText = '';
    if (unread && bodies.length > 0) {
      // Find the last unread message
      var annState = state[ann.id];
      var lastReadAt = annState && annState.lastReadAt;
      var lastReadDate = lastReadAt ? new Date(lastReadAt) : null;
      var lastUnreadMsg = null;
      for (var u = bodies.length - 1; u >= 0; u--) {
        if (!lastReadDate || (bodies[u].created && new Date(bodies[u].created) > lastReadDate)) {
          lastUnreadMsg = bodies[u];
          break;
        }
      }
      if (lastUnreadMsg && lastUnreadMsg.creator && lastUnreadMsg.creator.name === 'ai') {
        badgeText = 'AI reply';
      } else if (lastUnreadMsg) {
        badgeText = 'new reply';
      }
    }

    // Header
    var header = document.createElement('div');
    header.className = 'scholia-card-header';

    var anchorText = (ann.target && ann.target.selector && ann.target.selector.exact) || '(no anchor)';
    var anchorSpan = document.createElement('span');
    anchorSpan.className = 'scholia-anchor-text';
    anchorSpan.textContent = '\u201c' + anchorText.slice(0, 50) + (anchorText.length > 50 ? '\u2026' : '') + '\u201d';
    header.appendChild(anchorSpan);

    // Orphan label
    if (orphanIds.has(ann.id)) {
      var orphanLabel = document.createElement('span');
      orphanLabel.className = 'scholia-orphan-label';
      orphanLabel.textContent = 'anchor not found';
      header.appendChild(orphanLabel);
    }

    // Resolved label
    if (status === 'resolved') {
      var resolvedLabel = document.createElement('span');
      resolvedLabel.className = 'scholia-resolved-label';
      resolvedLabel.textContent = 'resolved';
      header.appendChild(resolvedLabel);
    }

    // Message count
    var countSpan = document.createElement('span');
    countSpan.className = 'scholia-msg-count';
    countSpan.textContent = bodies.length;
    header.appendChild(countSpan);

    // Unread badge
    if (badgeText) {
      var badge = document.createElement('span');
      badge.className = 'scholia-badge';
      badge.textContent = badgeText;
      header.appendChild(badge);
    }

    // Mark unread button (visible when thread is read)
    if (!unread && bodies.length > 0) {
      var markUnreadBtn = document.createElement('button');
      markUnreadBtn.className = 'scholia-btn-mark-unread';
      markUnreadBtn.textContent = 'mark unread';
      markUnreadBtn.addEventListener('click', function (e) {
        e.stopPropagation();
        wsSend({ type: 'mark_unread', annotation_id: ann.id });
        state[ann.id] = { lastReadAt: null };
        renderSidebar();
        positionCards();
      });
      header.appendChild(markUnreadBtn);
    }

    card.appendChild(header);

    // Thread (collapsed)
    var thread = document.createElement('div');
    thread.className = 'scholia-thread';
    thread.style.display = 'none';

    for (var j = 0; j < bodies.length; j++) {
      var msg = bodies[j];
      var msgEl = document.createElement('div');
      var role = (msg.creator && msg.creator.name) || 'unknown';
      msgEl.className = 'scholia-message scholia-' + role;

      var meta = document.createElement('div');
      meta.className = 'scholia-message-meta';
      meta.textContent = role;
      msgEl.appendChild(meta);

      var body = document.createElement('div');
      body.className = 'scholia-message-body';
      body.textContent = msg.value;
      msgEl.appendChild(body);

      thread.appendChild(msgEl);
    }

    // Reply input
    var replyRow = document.createElement('div');
    replyRow.className = 'scholia-reply-input';

    var replyTextarea = document.createElement('textarea');
    replyTextarea.placeholder = 'Reply\u2026';
    replyTextarea.rows = 1;
    replyRow.appendChild(replyTextarea);

    var replyBtn = document.createElement('button');
    replyBtn.textContent = 'Reply';
    replyBtn.addEventListener('click', function () {
      var text = replyTextarea.value.trim();
      if (!text) return;
      wsSend({
        type: 'reply',
        annotation_id: ann.id,
        body: text,
        creator: 'human'
      });
      replyTextarea.value = '';
    });
    replyRow.appendChild(replyBtn);

    thread.appendChild(replyRow);

    // Thread footer: resolve/unresolve
    var footer = document.createElement('div');
    footer.className = 'scholia-new-comment-actions';

    if (status === 'open') {
      var resolveBtn = document.createElement('button');
      resolveBtn.className = 'scholia-btn-resolve';
      resolveBtn.textContent = 'Resolve';
      resolveBtn.addEventListener('click', function (e) {
        e.stopPropagation();
        wsSend({ type: 'resolve', annotation_id: ann.id });
      });
      footer.appendChild(resolveBtn);
    } else if (status === 'resolved') {
      var unresolveBtn = document.createElement('button');
      unresolveBtn.className = 'scholia-btn-unresolve';
      unresolveBtn.textContent = 'Unresolve';
      unresolveBtn.addEventListener('click', function (e) {
        e.stopPropagation();
        wsSend({ type: 'unresolve', annotation_id: ann.id });
      });
      footer.appendChild(unresolveBtn);
    }

    thread.appendChild(footer);
    card.appendChild(thread);

    // Click header to expand/collapse
    header.addEventListener('click', function () {
      var open = thread.style.display !== 'none';
      thread.style.display = open ? 'none' : 'block';
      card.classList.toggle('scholia-expanded', !open);

      if (!open) {
        // Expanding: mark read
        card.classList.remove('scholia-unread');
        wsSend({ type: 'mark_read', annotation_id: ann.id });
        state[ann.id] = { lastReadAt: new Date().toISOString() };

        // Remove badge if present
        var existingBadge = card.querySelector('.scholia-badge');
        if (existingBadge) existingBadge.remove();

        // Scroll thread to bottom so latest message visible
        thread.scrollTop = thread.scrollHeight;

        // Scroll to anchor in document + pulse
        var marks = highlights.get(ann.id);
        if (marks && marks.length > 0) {
          marks[0].scrollIntoView({ behavior: 'smooth', block: 'center' });
          setTimeout(function () {
            for (var p = 0; p < marks.length; p++) {
              marks[p].classList.add('scholia-pulse');
            }
          }, 300);
          setTimeout(function () {
            for (var p = 0; p < marks.length; p++) {
              marks[p].classList.remove('scholia-pulse');
            }
          }, 900);
        }
      }
    });

    // Hover cross-link with anchor highlight
    card.addEventListener('mouseenter', function () { setAnchorHighlight(ann.id, true); });
    card.addEventListener('mouseleave', function () { setAnchorHighlight(ann.id, false); });

    return card;
  }

  // ── Anchor highlighting ────────────────────────────

  function reanchorAll() {
    // Remove existing highlights
    highlights.forEach(function (marks) {
      for (var i = 0; i < marks.length; i++) {
        var mark = marks[i];
        var parent = mark.parentNode;
        if (!parent) continue;
        while (mark.firstChild) parent.insertBefore(mark.firstChild, mark);
        parent.removeChild(mark);
      }
    });
    highlights.clear();
    orphanIds.clear();

    for (var i = 0; i < comments.length; i++) {
      var ann = comments[i];
      var selector = ann.target && ann.target.selector;
      if (!selector || !selector.exact) {
        orphanIds.add(ann.id);
        continue;
      }

      var range = TextQuoteAnchor.toRange(docEl, selector);
      if (!range) {
        orphanIds.add(ann.id);
        continue;
      }

      var marks = wrapRange(range, ann.id);
      if (marks.length) {
        highlights.set(ann.id, marks);
      } else {
        orphanIds.add(ann.id);
      }
    }

    // Update orphan classes on existing cards
    var cards = sidebarEl.querySelectorAll('.scholia-card');
    for (var c = 0; c < cards.length; c++) {
      var id = cards[c].dataset.annotationId;
      if (orphanIds.has(id)) {
        cards[c].classList.add('scholia-orphan');
      } else {
        cards[c].classList.remove('scholia-orphan');
      }
    }
  }

  function wrapRange(range, annId) {
    var marks = [];

    // Simple case: range is within a single text node
    try {
      var mark = document.createElement('mark');
      mark.className = 'scholia-highlight';
      mark.dataset.annotationId = annId;
      range.surroundContents(mark);
      marks.push(mark);
      return marks;
    } catch (e) {
      // Range spans multiple elements — wrap each text node segment
    }

    var walker = document.createTreeWalker(
      range.commonAncestorContainer,
      NodeFilter.SHOW_TEXT
    );
    var textNodes = [];
    while (walker.nextNode()) {
      if (range.intersectsNode(walker.currentNode)) {
        textNodes.push(walker.currentNode);
      }
    }

    for (var i = 0; i < textNodes.length; i++) {
      var node = textNodes[i];
      var mark = document.createElement('mark');
      mark.className = 'scholia-highlight';
      mark.dataset.annotationId = annId;

      var nodeRange = document.createRange();
      if (node === range.startContainer) {
        nodeRange.setStart(node, range.startOffset);
        nodeRange.setEnd(node, node.textContent.length);
      } else if (node === range.endContainer) {
        nodeRange.setStart(node, 0);
        nodeRange.setEnd(node, range.endOffset);
      } else {
        nodeRange.selectNodeContents(node);
      }

      try {
        nodeRange.surroundContents(mark);
        marks.push(mark);
      } catch (e) {
        // skip nodes that can't be wrapped
      }
    }

    return marks;
  }

  function setAnchorHighlight(annId, active) {
    var marks = highlights.get(annId);
    if (marks) {
      for (var i = 0; i < marks.length; i++) {
        marks[i].classList.toggle('scholia-highlight-active', active);
      }
    }
    var card = sidebarEl.querySelector('[data-annotation-id="' + annId + '"]');
    if (card) card.classList.toggle('scholia-card-linked', active);
  }

  // ── Card positioning ───────────────────────────────

  function positionCards() {
    var cards = sidebarEl.querySelectorAll('.scholia-card');
    if (!cards.length) return;

    var sidebarRect = sidebarEl.getBoundingClientRect();
    var sidebarScrollTop = sidebarEl.scrollTop;

    var positioned = [];
    var orphans = [];

    for (var i = 0; i < cards.length; i++) {
      var card = cards[i];
      var annId = card.dataset.annotationId;
      var marks = highlights.get(annId);

      if (!marks || marks.length === 0 || orphanIds.has(annId)) {
        orphans.push(card);
        continue;
      }

      // Compute anchor Y relative to the sidebar's coordinate space
      var markRect = marks[0].getBoundingClientRect();
      var anchorY = markRect.top - sidebarRect.top + sidebarScrollTop;
      positioned.push({ card: card, anchorY: anchorY });
    }

    // Sort by anchor Y position
    positioned.sort(function (a, b) { return a.anchorY - b.anchorY; });

    // Position cards with push-down for overlaps
    var currentY = 0;
    for (var p = 0; p < positioned.length; p++) {
      var entry = positioned[p];
      var targetY = Math.max(entry.anchorY, currentY);
      entry.card.style.position = 'relative';
      entry.card.style.top = targetY + 'px';
      entry.card.style.marginTop = '-' + entry.card.offsetHeight + 'px';
      // Recalculate: after placing, the next card should start below this one
      currentY = targetY + entry.card.offsetHeight + 4; // 4px gap
    }

    // Orphan cards: reset position, grouped at bottom
    for (var o = 0; o < orphans.length; o++) {
      orphans[o].style.position = '';
      orphans[o].style.top = '';
      orphans[o].style.marginTop = '';
    }
  }

  // ── Document hover → highlight linked card ─────────

  docEl.addEventListener('mouseover', function (e) {
    var mark = e.target.closest && e.target.closest('.scholia-highlight');
    if (!mark) return;
    setAnchorHighlight(mark.dataset.annotationId, true);
  });

  docEl.addEventListener('mouseout', function (e) {
    var mark = e.target.closest && e.target.closest('.scholia-highlight');
    if (!mark) return;
    setAnchorHighlight(mark.dataset.annotationId, false);
  });

  // ── Text selection → new comment ───────────────────

  docEl.addEventListener('mouseup', function () {
    var sel = window.getSelection();
    if (!sel || sel.isCollapsed || !sel.rangeCount) return;

    var range = sel.getRangeAt(0);
    if (!docEl.contains(range.commonAncestorContainer)) return;

    // Ignore if selection is inside an existing form
    if (range.commonAncestorContainer.closest &&
        range.commonAncestorContainer.closest('#scholia-new-comment')) return;

    var selector = TextQuoteAnchor.fromRange(docEl, range);
    if (!selector.exact.trim()) return;

    showCommentForm(selector);
  });

  function showCommentForm(selector) {
    var existing = document.getElementById('scholia-new-comment');
    if (existing) existing.remove();

    var form = document.createElement('div');
    form.id = 'scholia-new-comment';
    form.className = 'scholia-new-comment';

    var anchorDiv = document.createElement('div');
    anchorDiv.className = 'scholia-new-comment-anchor';
    var excerpt = selector.exact.slice(0, 80);
    anchorDiv.textContent = '\u201c' + excerpt + (selector.exact.length > 80 ? '\u2026' : '') + '\u201d';
    form.appendChild(anchorDiv);

    var textarea = document.createElement('textarea');
    textarea.placeholder = 'Add a comment\u2026';
    textarea.rows = 3;
    form.appendChild(textarea);

    var actions = document.createElement('div');
    actions.className = 'scholia-new-comment-actions';

    var cancelBtn = document.createElement('button');
    cancelBtn.className = 'scholia-btn scholia-btn-cancel';
    cancelBtn.textContent = 'Cancel';
    cancelBtn.addEventListener('click', function () {
      form.remove();
      window.getSelection().removeAllRanges();
    });
    actions.appendChild(cancelBtn);

    var submitBtn = document.createElement('button');
    submitBtn.className = 'scholia-btn scholia-btn-submit';
    submitBtn.textContent = 'Comment';
    submitBtn.addEventListener('click', function () {
      var text = textarea.value.trim();
      if (!text) return;
      wsSend({
        type: 'new_comment',
        exact: selector.exact,
        prefix: selector.prefix,
        suffix: selector.suffix,
        body: text
      });
      form.remove();
      window.getSelection().removeAllRanges();
    });
    actions.appendChild(submitBtn);

    form.appendChild(actions);

    // Insert at top of sidebar (after filter controls if present)
    var controlsEl = sidebarEl.querySelector('.scholia-sidebar-controls');
    if (controlsEl && controlsEl.nextSibling) {
      sidebarEl.insertBefore(form, controlsEl.nextSibling);
    } else if (controlsEl) {
      sidebarEl.appendChild(form);
    } else {
      sidebarEl.insertBefore(form, sidebarEl.firstChild);
    }
    textarea.focus();
  }

  // ── Init ───────────────────────────────────────────

  connectWS();
  renderSidebar();

  // KaTeX is loaded with defer, so wait for window load before rendering math
  window.addEventListener('load', function () {
    rerenderMath();
    decorateCodeBlocks();
    reanchorAll();
    positionCards();
  });

})();

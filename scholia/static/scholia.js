/**
 * Scholia frontend: sidebar, text selection → comments, WebSocket live reload,
 * anchor highlighting with cross-linked hover.
 */
(function () {
  'use strict';

  var ws;
  var comments = window.__SCHOLIA_COMMENTS__ || [];
  var docEl = document.getElementById('scholia-doc');
  var sidebarEl = document.getElementById('scholia-sidebar');
  var highlights = new Map();   // annotation id → [mark elements]

  // ── WebSocket ────────────────────────────────────────

  function connectWS() {
    var proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
    ws = new WebSocket(proto + '//' + location.host + '/ws');

    ws.onmessage = function (e) {
      var msg = JSON.parse(e.data);
      if (msg.type === 'doc_update') {
        docEl.innerHTML = msg.html;
        rerenderMath();
        reanchorAll();
      } else if (msg.type === 'comments_update') {
        comments = msg.comments;
        renderSidebar();
        reanchorAll();
      }
    };

    ws.onclose = function () {
      setTimeout(connectWS, 2000);
    };
  }

  // ── Math rendering ───────────────────────────────────

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

  // ── Sidebar ──────────────────────────────────────────

  function renderSidebar() {
    // Preserve any open new-comment form
    var existingForm = document.getElementById('scholia-new-comment');

    sidebarEl.innerHTML = '';

    if (existingForm) {
      sidebarEl.appendChild(existingForm);
    }

    if (comments.length === 0) {
      var empty = document.createElement('div');
      empty.className = 'scholia-empty';
      empty.textContent = 'No comments yet. Select text to add one.';
      sidebarEl.appendChild(empty);
      return;
    }

    for (var i = 0; i < comments.length; i++) {
      sidebarEl.appendChild(createCard(comments[i]));
    }
  }

  function createCard(ann) {
    var card = document.createElement('div');
    card.className = 'scholia-card';
    card.dataset.annotationId = ann.id;

    var status = ann['scholia:status'] || 'open';
    if (status === 'open') card.classList.add('scholia-open');

    // Detect unread AI reply (last message is from AI)
    var bodies = ann.body || [];
    var lastMsg = bodies[bodies.length - 1];
    var hasUnreadAI = lastMsg && lastMsg.creator && lastMsg.creator.name === 'ai';
    if (hasUnreadAI) card.classList.add('scholia-unread');

    // Header
    var header = document.createElement('div');
    header.className = 'scholia-card-header';

    var anchorText = (ann.target && ann.target.selector && ann.target.selector.exact) || '(no anchor)';
    var anchorSpan = document.createElement('span');
    anchorSpan.className = 'scholia-anchor-text';
    anchorSpan.textContent = '"' + anchorText.slice(0, 50) + (anchorText.length > 50 ? '…' : '') + '"';
    header.appendChild(anchorSpan);

    // Message count
    var countSpan = document.createElement('span');
    countSpan.className = 'scholia-msg-count';
    countSpan.textContent = bodies.length;
    header.appendChild(countSpan);

    // Unread badge
    if (hasUnreadAI) {
      var badge = document.createElement('span');
      badge.className = 'scholia-badge';
      badge.textContent = 'AI reply';
      badge.addEventListener('click', function (e) {
        e.stopPropagation();
        card.classList.remove('scholia-unread');
      });
      header.appendChild(badge);
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

    card.appendChild(thread);

    // Click header to expand/collapse
    header.addEventListener('click', function () {
      var open = thread.style.display !== 'none';
      thread.style.display = open ? 'none' : 'block';
      card.classList.toggle('scholia-expanded', !open);
      if (!open) {
        card.classList.remove('scholia-unread');
        // Scroll thread to bottom so latest message visible
        thread.scrollTop = thread.scrollHeight;
      }
    });

    // Hover cross-link with anchor highlight
    card.addEventListener('mouseenter', function () { setAnchorHighlight(ann.id, true); });
    card.addEventListener('mouseleave', function () { setAnchorHighlight(ann.id, false); });

    return card;
  }

  // ── Anchor highlighting ──────────────────────────────

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

    for (var i = 0; i < comments.length; i++) {
      var ann = comments[i];
      var selector = ann.target && ann.target.selector;
      if (!selector || !selector.exact) continue;

      var range = TextQuoteAnchor.toRange(docEl, selector);
      if (!range) continue;

      var marks = wrapRange(range, ann.id);
      if (marks.length) highlights.set(ann.id, marks);
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

  // ── Document hover → highlight linked card ───────────

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

  // ── Text selection → new comment ─────────────────────

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
    anchorDiv.textContent = '"' + excerpt + (selector.exact.length > 80 ? '…' : '') + '"';
    form.appendChild(anchorDiv);

    var textarea = document.createElement('textarea');
    textarea.placeholder = 'Add a comment…';
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
      if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({
          type: 'new_comment',
          exact: selector.exact,
          prefix: selector.prefix,
          suffix: selector.suffix,
          body: text,
        }));
      }
      form.remove();
      window.getSelection().removeAllRanges();
    });
    actions.appendChild(submitBtn);

    form.appendChild(actions);

    // Insert at top of sidebar
    sidebarEl.insertBefore(form, sidebarEl.firstChild);
    textarea.focus();
  }

  // ── Init ─────────────────────────────────────────────

  connectWS();
  renderSidebar();

  // KaTeX is loaded with defer, so wait for window load before rendering math
  window.addEventListener('load', function () {
    rerenderMath();
    reanchorAll();
  });

})();

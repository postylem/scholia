/**
 * Scholia frontend v0.2: sidebar, text selection, WebSocket live reload,
 * anchor highlighting, read/unread state, reply, resolve, code chrome,
 * positioned cards with orphan handling.
 */
(function () {
  'use strict';

  var ws;
  var creatorName = window.__SCHOLIA_CREATOR__ || 'human';
  var comments = window.__SCHOLIA_COMMENTS__ || [];
  var state = window.__SCHOLIA_STATE__ || {};
  var docEl = document.getElementById('scholia-doc');
  var sidebarEl = document.getElementById('scholia-sidebar');
  var highlights = new Map();   // annotation id → [mark elements]
  var orphanIds = new Set();
  var filterMode = 'open';      // 'open' or 'all'
  var expandOverrides = {};     // annotation id → boolean (user manual toggle)

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
        setupCitationTooltips();
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

  // ── Comment body rendering (inline code + KaTeX) ──

  function escapeHtml(s) {
    return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  }

  function renderCommentBody(text) {
    var out = '';
    var i = 0;
    var hasKatex = !!window.katex;

    while (i < text.length) {
      // Inline code: `...`
      if (text[i] === '`') {
        var end = text.indexOf('`', i + 1);
        if (end !== -1) {
          out += '<code>' + escapeHtml(text.slice(i + 1, end)) + '</code>';
          i = end + 1;
          continue;
        }
      }
      // Display math: $$...$$
      if (text[i] === '$' && text[i + 1] === '$') {
        var end = text.indexOf('$$', i + 2);
        if (end !== -1) {
          var tex = text.slice(i + 2, end);
          if (hasKatex) {
            try { out += katex.renderToString(tex, { displayMode: true, throwOnError: false }); }
            catch (e) { out += '<code>' + escapeHtml(tex) + '</code>'; }
          } else {
            out += '<code>' + escapeHtml(tex) + '</code>';
          }
          i = end + 2;
          continue;
        }
      }
      // Inline math: $...$
      if (text[i] === '$') {
        var end = text.indexOf('$', i + 1);
        if (end !== -1 && end > i + 1) {
          var tex = text.slice(i + 1, end);
          if (hasKatex) {
            try { out += katex.renderToString(tex, { displayMode: false, throwOnError: false }); }
            catch (e) { out += '<code>' + escapeHtml(tex) + '</code>'; }
          } else {
            out += '<code>' + escapeHtml(tex) + '</code>';
          }
          i = end + 1;
          continue;
        }
      }
      // Plain text until next special char
      var next = i + 1;
      while (next < text.length && text[next] !== '$' && text[next] !== '`') next++;
      out += escapeHtml(text.slice(i, next));
      i = next;
    }
    return out;
  }

  function rerenderCommentBodies() {
    if (!window.katex) return;
    var bodies = sidebarEl.querySelectorAll('.scholia-message-body');
    for (var i = 0; i < bodies.length; i++) {
      var raw = bodies[i].dataset.raw;
      if (raw !== undefined) bodies[i].innerHTML = renderCommentBody(raw);
    }
  }

  // ── Unread detection ───────────────────────────────

  function isUnread(ann) {
    var bodies = ann.body || [];
    if (bodies.length === 0) return false;

    // If the last message is by a human (not AI), they've seen everything
    var lastBody = bodies[bodies.length - 1];
    var lastCreator = lastBody.creator && lastBody.creator.name;
    if (lastCreator !== 'ai') return false;

    // No read timestamp and last msg is not human → unread
    var annState = state[ann.id];
    var lastReadAt = annState && annState.lastReadAt;
    if (!lastReadAt) return true;

    var lastReadDate = new Date(lastReadAt);
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
      reanchorAll();
      positionCards();
    });
    controls.appendChild(openBtn);

    var allBtn = document.createElement('button');
    allBtn.className = 'scholia-filter-btn' + (filterMode === 'all' ? ' active' : '');
    allBtn.textContent = 'All';
    allBtn.addEventListener('click', function () {
      filterMode = 'all';
      renderSidebar();
      reanchorAll();
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
    var bodies = ann.body || [];

    var status = ann['scholia:status'] || 'open';
    if (status === 'open') card.classList.add('scholia-open');
    if (status === 'resolved') card.classList.add('scholia-resolved');

    // Orphan detection
    if (orphanIds.has(ann.id)) {
      card.classList.add('scholia-orphan');
    }

    // AI-replied detection: has any reply from AI
    var hasAiReply = false;
    for (var b = 0; b < bodies.length; b++) {
      if (bodies[b].creator && bodies[b].creator.name === 'ai') {
        hasAiReply = true;
        break;
      }
    }
    if (hasAiReply) card.classList.add('scholia-ai-replied');

    // Unread detection (timestamp-based)
    var unread = isUnread(ann);
    if (unread) card.classList.add('scholia-unread');

    // Determine unread badge text
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

    // Orphan icon
    if (orphanIds.has(ann.id)) {
      var orphanIcon = document.createElement('span');
      orphanIcon.className = 'scholia-orphan-icon';
      orphanIcon.textContent = '?';
      orphanIcon.title = 'Anchor text not found in document';
      header.appendChild(orphanIcon);
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
      var msgCreator = (msg.creator && msg.creator.name) || 'unknown';
      var role = msgCreator === 'ai' ? 'ai' : 'human';
      msgEl.className = 'scholia-message scholia-' + role;

      var meta = document.createElement('div');
      meta.className = 'scholia-message-meta';
      meta.textContent = msgCreator;
      msgEl.appendChild(meta);

      var body = document.createElement('div');
      body.className = 'scholia-message-body';
      body.dataset.raw = msg.value;
      body.innerHTML = renderCommentBody(msg.value);
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
        creator: creatorName
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
      var wasExpanded = card.classList.contains('scholia-expanded');
      expandOverrides[ann.id] = !wasExpanded;

      if (!wasExpanded) {
        // About to expand: mark read
        card.classList.remove('scholia-unread');
        wsSend({ type: 'mark_read', annotation_id: ann.id });
        state[ann.id] = { lastReadAt: new Date().toISOString() };
        var existingBadge = card.querySelector('.scholia-badge');
        if (existingBadge) existingBadge.remove();
      }

      // Reposition all cards (sets expand state via positionCards)
      positionCards();

      if (!wasExpanded) {
        // Now expanded: scroll thread to bottom
        thread.scrollTop = thread.scrollHeight;

        // Scroll page so anchor is ~10% from viewport top
        var marks = highlights.get(ann.id);
        if (marks && marks.length > 0) {
          var markPageY = marks[0].getBoundingClientRect().top + window.scrollY;
          var targetScrollY = markPageY - window.innerHeight * 0.1;
          window.scrollTo({ top: Math.max(0, targetScrollY), behavior: 'smooth' });

          setTimeout(function () {
            for (var p = 0; p < marks.length; p++) marks[p].classList.add('scholia-pulse');
          }, 300);
          setTimeout(function () {
            for (var p = 0; p < marks.length; p++) marks[p].classList.remove('scholia-pulse');
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
      var status = ann['scholia:status'] || 'open';

      // Skip resolved comments in 'open' filter mode
      if (filterMode === 'open' && status === 'resolved') continue;

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
        // Resolved threads get a muted highlight style
        if (status === 'resolved') {
          for (var m = 0; m < marks.length; m++) {
            marks[m].classList.add('scholia-highlight-resolved');
          }
        }
        highlights.set(ann.id, marks);
      } else {
        orphanIds.add(ann.id);
      }
    }

    // Update orphan classes and icons on existing cards
    var cards = sidebarEl.querySelectorAll('.scholia-card');
    for (var c = 0; c < cards.length; c++) {
      var id = cards[c].dataset.annotationId;
      var headerEl = cards[c].querySelector('.scholia-card-header');
      var existingIcon = cards[c].querySelector('.scholia-orphan-icon');
      if (orphanIds.has(id)) {
        cards[c].classList.add('scholia-orphan');
        if (!existingIcon && headerEl) {
          var icon = document.createElement('span');
          icon.className = 'scholia-orphan-icon';
          icon.textContent = '?';
          icon.title = 'Anchor text not found in document';
          // Insert after anchor text span
          var anchorSpan = headerEl.querySelector('.scholia-anchor-text');
          if (anchorSpan && anchorSpan.nextSibling) {
            headerEl.insertBefore(icon, anchorSpan.nextSibling);
          } else {
            headerEl.appendChild(icon);
          }
        }
      } else {
        cards[c].classList.remove('scholia-orphan');
        if (existingIcon) existingIcon.remove();
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
  // Cards are absolutely positioned within the sidebar (position: relative)
  // so they align vertically with their anchor highlights in the document.
  // Both columns scroll together as part of the same page flow.
  //
  // Auto-expand: threads default to expanded unless that would push the
  // next thread below its anchor. User manual toggles override auto logic.

  function positionCards() {
    var cards = sidebarEl.querySelectorAll('.scholia-card');
    if (!cards.length) { updateOffscreenIndicators(); return; }

    var sidebarTop = sidebarEl.getBoundingClientRect().top;

    // Reserve space for controls and new-comment form
    var controlsEl = sidebarEl.querySelector('.scholia-sidebar-controls');
    var newCommentEl = document.getElementById('scholia-new-comment');
    var minY = parseFloat(getComputedStyle(sidebarEl).paddingTop) || 0;
    if (controlsEl) {
      minY = controlsEl.getBoundingClientRect().bottom - sidebarTop;
    }
    if (newCommentEl) {
      var ncBottom = newCommentEl.getBoundingClientRect().bottom - sidebarTop;
      if (ncBottom > minY) minY = ncBottom;
    }
    minY += 4;

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

      var anchorY = marks[0].getBoundingClientRect().top - sidebarTop;
      positioned.push({ card: card, annId: annId, anchorY: anchorY });
    }

    positioned.sort(function (a, b) { return a.anchorY - b.anchorY; });

    // Make all cards absolute so widths compute correctly
    var allCards = positioned.map(function (p) { return p.card; }).concat(orphans);
    for (var i = 0; i < allCards.length; i++) {
      allCards[i].style.position = 'absolute';
      allCards[i].style.left = '0.75rem';
      allCards[i].style.right = '0.75rem';
      allCards[i].style.margin = '0';
    }

    // Measure collapsed and expanded heights for each anchored card
    for (var p = 0; p < positioned.length; p++) {
      var entry = positioned[p];
      var thread = entry.card.querySelector('.scholia-thread');
      if (thread) {
        var prev = thread.style.display;
        thread.style.display = 'none';
        entry.collapsedH = entry.card.offsetHeight;
        thread.style.display = 'block';
        entry.expandedH = entry.card.offsetHeight;
        thread.style.display = prev;
      } else {
        entry.collapsedH = entry.card.offsetHeight;
        entry.expandedH = entry.card.offsetHeight;
      }
    }

    // Forward pass: decide expand state and position
    var currentY = minY;
    for (var p = 0; p < positioned.length; p++) {
      var entry = positioned[p];
      var top = Math.max(entry.anchorY, currentY);
      var thread = entry.card.querySelector('.scholia-thread');

      var override = expandOverrides[entry.annId];
      var shouldExpand;
      if (override !== undefined) {
        shouldExpand = override;
      } else {
        // Auto-expand unless it would push next card past its anchor
        var nextAnchorY = (p + 1 < positioned.length) ? positioned[p + 1].anchorY : Infinity;
        shouldExpand = (top + entry.expandedH + 4 <= nextAnchorY);
      }

      if (thread) thread.style.display = shouldExpand ? 'block' : 'none';
      entry.card.classList.toggle('scholia-expanded', shouldExpand);

      entry.card.style.top = top + 'px';
      currentY = top + (shouldExpand ? entry.expandedH : entry.collapsedH) + 4;
    }

    // Orphan cards after all positioned ones (respect user overrides)
    for (var o = 0; o < orphans.length; o++) {
      var oId = orphans[o].dataset.annotationId;
      var oThread = orphans[o].querySelector('.scholia-thread');
      var oExpanded = expandOverrides[oId] === true;
      if (oThread) oThread.style.display = oExpanded ? 'block' : 'none';
      orphans[o].classList.toggle('scholia-expanded', oExpanded);
      orphans[o].style.top = currentY + 'px';
      currentY += orphans[o].offsetHeight + 4;
    }

    sidebarEl.style.minHeight = currentY + 'px';
    updateOffscreenIndicators();
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
  // Flow: user selects text → lightweight prompt appears in sidebar aligned
  // with the selection → native selection stays visible (no yellow highlight yet).
  // If user clicks elsewhere or deselects, prompt disappears.
  // If user clicks the prompt or starts typing, it activates: native selection
  // is replaced with yellow highlight marks and the textarea gets focus.

  var pendingForm = null;
  var pendingSelector = null;

  docEl.addEventListener('mouseup', function () {
    var sel = window.getSelection();
    if (!sel || sel.isCollapsed || !sel.rangeCount) return;

    var range = sel.getRangeAt(0);
    if (!docEl.contains(range.commonAncestorContainer)) return;

    // Ignore if inside the comment form
    if (pendingForm && pendingForm.contains(range.commonAncestorContainer)) return;

    var selector = TextQuoteAnchor.fromRange(docEl, range);
    if (!selector.exact.trim()) return;

    // Position: at selection top, or viewport top if selection starts off-screen
    var rangeRect = range.getBoundingClientRect();
    var sidebarTop = sidebarEl.getBoundingClientRect().top;
    var trueAnchorY = rangeRect.top - sidebarTop;
    var initialY = Math.max(rangeRect.top, 0) - sidebarTop;
    showCommentPrompt(selector, initialY, trueAnchorY);
  });

  function showCommentPrompt(selector, initialY, trueAnchorY) {
    dismissCommentPrompt();
    pendingSelector = selector;

    var form = document.createElement('div');
    form.id = 'scholia-new-comment';
    form.className = 'scholia-new-comment';
    form.style.position = 'absolute';
    form.style.left = '0.75rem';
    form.style.right = '0.75rem';
    form.style.top = initialY + 'px';
    form.style.margin = '0';
    form.dataset.trueY = trueAnchorY;

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
    cancelBtn.addEventListener('click', function (e) {
      e.stopPropagation();
      dismissCommentPrompt();
      window.getSelection().removeAllRanges();
    });
    actions.appendChild(cancelBtn);

    var submitBtn = document.createElement('button');
    submitBtn.className = 'scholia-btn scholia-btn-submit';
    submitBtn.textContent = 'Comment';
    submitBtn.addEventListener('click', function (e) {
      e.stopPropagation();
      var text = textarea.value.trim();
      if (!text) return;

      var doSend = function () {
        wsSend({
          type: 'new_comment',
          exact: pendingSelector.exact,
          prefix: pendingSelector.prefix,
          suffix: pendingSelector.suffix,
          body: text
        });
        dismissCommentPrompt();
        window.getSelection().removeAllRanges();
      };

      // Animate form to true anchor position if it was offset
      var trueY = parseFloat(form.dataset.trueY);
      var currentY = parseFloat(form.style.top);
      if (Math.abs(trueY - currentY) > 1) {
        form.style.transition = 'top 0.3s ease';
        form.style.top = trueY + 'px';
        setTimeout(doSend, 300);
      } else {
        doSend();
      }
    });
    actions.appendChild(submitBtn);

    form.appendChild(actions);
    sidebarEl.appendChild(form);
    pendingForm = form;

    // When textarea gets focus (click or forwarded keypress), activate highlight
    textarea.addEventListener('focus', function () {
      if (!pendingSelector) return;
      // Already activated?
      if (highlights.has('__pending__')) return;
      var r = TextQuoteAnchor.toRange(docEl, pendingSelector);
      if (r) {
        window.getSelection().removeAllRanges();
        var marks = wrapRange(r, '__pending__');
        highlights.set('__pending__', marks);
      }
    });
  }

  function dismissCommentPrompt() {
    if (pendingForm) {
      pendingForm.remove();
      pendingForm = null;
    }
    pendingSelector = null;
    // Remove pending highlight marks
    var marks = highlights.get('__pending__');
    if (marks) {
      for (var i = 0; i < marks.length; i++) {
        var m = marks[i];
        var p = m.parentNode;
        if (p) {
          while (m.firstChild) p.insertBefore(m.firstChild, m);
          p.removeChild(m);
        }
      }
      highlights.delete('__pending__');
    }
  }

  // Dismiss on mousedown outside the form
  document.addEventListener('mousedown', function (e) {
    if (!pendingForm) return;
    if (pendingForm.contains(e.target)) return;
    dismissCommentPrompt();
  });

  // Forward keyboard to textarea when prompt is visible but not focused
  document.addEventListener('keydown', function (e) {
    if (!pendingForm) return;
    var textarea = pendingForm.querySelector('textarea');
    if (!textarea || document.activeElement === textarea) return;

    if (e.key === 'Escape') {
      dismissCommentPrompt();
      window.getSelection().removeAllRanges();
      return;
    }

    // Printable character → focus textarea and insert the character
    if (e.key.length === 1 && !e.ctrlKey && !e.metaKey) {
      e.preventDefault();
      textarea.focus();
      textarea.value = e.key;
      textarea.selectionStart = textarea.selectionEnd = 1;
    }
  });

  // Dismiss if native selection is cleared while prompt is idle
  document.addEventListener('selectionchange', function () {
    if (!pendingForm) return;
    var textarea = pendingForm.querySelector('textarea');
    if (textarea && document.activeElement === textarea) return;
    var sel = window.getSelection();
    if (!sel || sel.isCollapsed) dismissCommentPrompt();
  });

  // ── Citation hover tooltips ─────────────────────────

  var citationTooltip = null;
  var citationHideTimer = null;

  function setupCitationTooltips() {
    // Pandoc with link-citations creates <a href="#ref-KEY"> inside <span class="citation">
    var links = docEl.querySelectorAll('a[href^="#ref-"]');
    for (var i = 0; i < links.length; i++) {
      links[i].addEventListener('mouseenter', showCitationTooltip);
      links[i].addEventListener('mouseleave', scheduleCitationHide);
      // Prevent clicking the citation from jumping to the bibliography
      // when the tooltip is showing (user likely wants to interact with tooltip)
      links[i].addEventListener('click', function (e) {
        if (citationTooltip) e.preventDefault();
      });
    }
  }

  function showCitationTooltip(e) {
    var link = e.target.closest('a[href^="#ref-"]');
    if (!link) return;
    var refId = link.getAttribute('href').slice(1); // strip #
    var refEl = document.getElementById(refId);
    if (!refEl) return;

    clearTimeout(citationHideTimer);
    removeCitationTooltip();

    citationTooltip = document.createElement('div');
    citationTooltip.className = 'scholia-citation-tooltip';
    citationTooltip.innerHTML = refEl.innerHTML;

    // Keep tooltip alive while hovering it
    citationTooltip.addEventListener('mouseenter', function () {
      clearTimeout(citationHideTimer);
    });
    citationTooltip.addEventListener('mouseleave', scheduleCitationHide);

    document.body.appendChild(citationTooltip);

    var rect = link.getBoundingClientRect();
    var tipRect = citationTooltip.getBoundingClientRect();
    var left = rect.left + rect.width / 2 - tipRect.width / 2;
    // Clamp to viewport
    left = Math.max(8, Math.min(left, window.innerWidth - tipRect.width - 8));
    var top = rect.top - tipRect.height - 8;
    if (top < 8) top = rect.bottom + 8; // flip below if no room above

    citationTooltip.style.left = left + 'px';
    citationTooltip.style.top = top + 'px';
    citationTooltip.style.opacity = '1';
  }

  function scheduleCitationHide() {
    clearTimeout(citationHideTimer);
    citationHideTimer = setTimeout(removeCitationTooltip, 300);
  }

  function removeCitationTooltip() {
    if (citationTooltip) {
      citationTooltip.remove();
      citationTooltip = null;
    }
  }

  // ── Offscreen thread indicators ────────────────────

  var aboveIndicator = document.createElement('div');
  aboveIndicator.className = 'scholia-offscreen-indicator scholia-offscreen-above';
  document.body.appendChild(aboveIndicator);

  var belowIndicator = document.createElement('div');
  belowIndicator.className = 'scholia-offscreen-indicator scholia-offscreen-below';
  document.body.appendChild(belowIndicator);

  // Click to scroll to nearest offscreen thread
  aboveIndicator.addEventListener('click', function () {
    var cards = sidebarEl.querySelectorAll('.scholia-card');
    // Find the last card that's above the viewport (closest to view)
    var target = null;
    for (var i = cards.length - 1; i >= 0; i--) {
      if (cards[i].getBoundingClientRect().bottom < 0) { target = cards[i]; break; }
    }
    if (target) scrollCardIntoView(target);
  });

  belowIndicator.addEventListener('click', function () {
    var cards = sidebarEl.querySelectorAll('.scholia-card');
    var viewH = window.innerHeight;
    // Find the first card that's below the viewport
    var target = null;
    for (var i = 0; i < cards.length; i++) {
      if (cards[i].getBoundingClientRect().top > viewH) { target = cards[i]; break; }
    }
    if (target) scrollCardIntoView(target);
  });

  function scrollCardIntoView(card) {
    var cardH = card.offsetHeight;
    var viewH = window.innerHeight;
    var cardPageY = card.getBoundingClientRect().top + window.scrollY;
    // If card fits in viewport, scroll so it's fully visible (centered-ish)
    // If too tall, scroll so its top is at the top of the viewport
    var scrollTarget;
    if (cardH <= viewH) {
      scrollTarget = cardPageY - (viewH - cardH) / 2;
    } else {
      scrollTarget = cardPageY;
    }
    window.scrollTo({ top: Math.max(0, scrollTarget), behavior: 'smooth' });
  }

  function updateOffscreenIndicators() {
    var cards = sidebarEl.querySelectorAll('.scholia-card');
    var viewH = window.innerHeight;
    var above = 0, aboveOrph = 0, below = 0, belowOrph = 0;

    for (var i = 0; i < cards.length; i++) {
      var r = cards[i].getBoundingClientRect();
      var isOrph = cards[i].classList.contains('scholia-orphan');
      if (r.bottom < 0) { above++; if (isOrph) aboveOrph++; }
      else if (r.top > viewH) { below++; if (isOrph) belowOrph++; }
    }

    // Align indicators with sidebar
    var sr = sidebarEl.getBoundingClientRect();
    aboveIndicator.style.left = sr.left + 'px';
    aboveIndicator.style.width = sr.width + 'px';
    belowIndicator.style.left = sr.left + 'px';
    belowIndicator.style.width = sr.width + 'px';

    if (above > 0) {
      aboveIndicator.style.display = 'block';
      var t = above + ' more thread' + (above !== 1 ? 's' : '');
      if (aboveOrph) t += ' (' + aboveOrph + ' orphan' + (aboveOrph !== 1 ? 's' : '') + ')';
      aboveIndicator.textContent = '\u2191 ' + t;
    } else {
      aboveIndicator.style.display = 'none';
    }

    if (below > 0) {
      belowIndicator.style.display = 'block';
      var t = below + ' more thread' + (below !== 1 ? 's' : '');
      if (belowOrph) t += ' (' + belowOrph + ' orphan' + (belowOrph !== 1 ? 's' : '') + ')';
      belowIndicator.textContent = '\u2193 ' + t;
    } else {
      belowIndicator.style.display = 'none';
    }
  }

  var scrollRaf = false;
  window.addEventListener('scroll', function () {
    if (!scrollRaf) {
      scrollRaf = true;
      requestAnimationFrame(function () {
        updateOffscreenIndicators();
        scrollRaf = false;
      });
    }
  }, { passive: true });

  // ── Init ───────────────────────────────────────────

  connectWS();
  renderSidebar();

  // KaTeX is loaded with defer, so wait for window load before rendering math
  window.addEventListener('load', function () {
    rerenderMath();
    rerenderCommentBodies();
    decorateCodeBlocks();
    setupCitationTooltips();
    reanchorAll();
    positionCards();
  });

  // Reposition cards on resize (layout may change)
  window.addEventListener('resize', positionCards);

})();

/**
 * Scholia frontend: sidebar, text selection, WebSocket live reload,
 * anchor highlighting, read/unread state, reply, resolve, edit,
 * positioned cards with orphan handling.
 */
(function () {
  'use strict';

  var ws;
  var wsAttempt = 0;
  var creatorName = window.__SCHOLIA_CREATOR__ || 'human';
  var comments = window.__SCHOLIA_COMMENTS__ || [];
  var state = window.__SCHOLIA_STATE__ || {};
  var docEl = document.getElementById('scholia-doc');
  var sidebarEl = document.getElementById('scholia-sidebar');
  var containerEl = document.getElementById('scholia-container');
  var toolbarEl = document.getElementById('scholia-toolbar');
  var resizeHandle = document.getElementById('scholia-resize-handle');
  var highlights = new Map();   // annotation id → [mark elements]
  var orphanIds = new Set();
  var showResolved = false;
  var showRead = true;
  var expandOverrides = {};     // annotation id → boolean (user manual toggle)
  var sidebarHidden = false;
  var compactMode = false;   // auto-set when viewport too narrow for sidebar
  var themeMode = localStorage.getItem('scholia-theme') || 'system'; // 'light' | 'dark' | 'system'
  var darkMode = themeMode === 'dark' || (themeMode === 'system' && window.matchMedia('(prefers-color-scheme: dark)').matches);
  var fontMode = localStorage.getItem('scholia-font') || 'default';  // 'default' | 'system' | 'latex'
  var uiZoom = parseInt(localStorage.getItem('scholia-zoom'), 10) || 100;
  var sidenotesEnabled = window.__SCHOLIA_SIDENOTES__ || false;
  var readonlyMode = window.__SCHOLIA_READONLY__ || false;

  var MD_EXTENSIONS = ['.md', '.markdown', '.qmd', '.rmd'];

  function abbreviatePath(p, maxLen) {
    if (p.length <= maxLen) return p;
    var parts = p.split('/').filter(function (s) { return s !== ''; });
    if (parts.length <= 3) return p;
    var first = parts[0];
    var last2 = parts.slice(-2).join('/');
    return '/' + first + '/[...]/' + last2 + '/';
  }

  function isMarkdownExt(name) {
    var lower = name.toLowerCase();
    for (var i = 0; i < MD_EXTENSIONS.length; i++) {
      if (lower.endsWith(MD_EXTENSIONS[i])) return true;
    }
    return false;
  }

  // ── Breadcrumb dropdown file browser ─────────────────

  var activeBreadcrumbDropdown = null;

  function closeBreadcrumbDropdown() {
    if (activeBreadcrumbDropdown) {
      activeBreadcrumbDropdown.dropdown.remove();
      activeBreadcrumbDropdown.seg.classList.remove('active');
      activeBreadcrumbDropdown = null;
    }
  }

  function openBreadcrumbDropdown(segEl, dirPath) {
    if (activeBreadcrumbDropdown && activeBreadcrumbDropdown.seg === segEl) {
      closeBreadcrumbDropdown();
      return;
    }
    closeAllDropdowns();

    var dropdown = document.createElement('div');
    dropdown.className = 'scholia-breadcrumb-dropdown';
    segEl.classList.add('active');

    // Append to body to escape overflow:hidden on toolbar-path
    document.body.appendChild(dropdown);
    var rect = segEl.getBoundingClientRect();
    dropdown.style.position = 'fixed';
    dropdown.style.top = rect.bottom + 4 + 'px';
    dropdown.style.left = rect.left + 'px';

    activeBreadcrumbDropdown = {seg: segEl, dropdown: dropdown};

    loadDirIntoDropdown(dropdown, dirPath);
  }

  function loadDirIntoDropdown(dropdown, dirPath) {
    dropdown.innerHTML = '';

    var header = document.createElement('div');
    header.className = 'scholia-breadcrumb-dropdown-header';
    header.textContent = abbreviatePath(dirPath, 50);
    header.title = dirPath;
    dropdown.appendChild(header);

    var body = document.createElement('div');
    body.className = 'scholia-breadcrumb-dropdown-body';
    body.textContent = 'Loading...';
    dropdown.appendChild(body);

    fetch('/api/list-dir?path=' + encodeURIComponent(dirPath))
      .then(function (r) { return r.json(); })
      .then(function (data) {
        if (data.error) {
          body.textContent = data.error;
          return;
        }
        body.innerHTML = '';
        var docFullPath = window.__SCHOLIA_DOC_FULLPATH__ || '';
        var docDisplayPath = window.__SCHOLIA_DOC_PATH__ || '';

        // Derive launch_dir so we can build relative ?file= links
        var launchDir = '';
        if (docDisplayPath && docFullPath.endsWith(docDisplayPath)) {
          launchDir = docFullPath.substring(0, docFullPath.length - docDisplayPath.length);
          if (launchDir.endsWith('/')) launchDir = launchDir.substring(0, launchDir.length - 1);
        }

        data.entries.forEach(function (entry) {
          var el;
          var entryFullPath = dirPath.replace(/\/$/, '') + '/' + entry.name;

          if (entry.type === 'dir' || entry.name === '..') {
            el = document.createElement('div');
            el.className = 'scholia-breadcrumb-entry scholia-breadcrumb-entry-dir';
            el.textContent = entry.name === '..' ? '..' : entry.name + '/';
            var chevron = document.createElement('span');
            chevron.className = 'scholia-breadcrumb-dir-chevron';
            chevron.textContent = ' \u203A';
            el.appendChild(chevron);
            var targetDir = entry.name === '..'
              ? dirPath.replace(/\/$/, '').replace(/\/[^/]+$/, '') || '/'
              : entryFullPath;
            el.addEventListener('click', function (e) {
              e.stopPropagation();
              loadDirIntoDropdown(dropdown, targetDir);
            });
            if (entry.name !== '..' && docFullPath.indexOf(entryFullPath + '/') === 0) {
              el.classList.add('scholia-breadcrumb-current-dir');
            }
          } else {
            el = document.createElement('a');
            el.className = 'scholia-breadcrumb-entry scholia-breadcrumb-entry-file';
            // Use relative path when under launch_dir, readable slashes always
            var fileParam = entryFullPath;
            if (launchDir && entryFullPath.indexOf(launchDir + '/') === 0) {
              fileParam = entryFullPath.substring(launchDir.length + 1);
            }
            el.href = '/?file=' + encodeURIComponent(fileParam).replace(/%2F/g, '/');
            el.textContent = entry.name;
            if (!isMarkdownExt(entry.name)) {
              el.classList.add('scholia-breadcrumb-entry-dimmed');
            }
            if (entryFullPath === docFullPath) {
              el.classList.add('scholia-breadcrumb-current-file');
              var badge = document.createElement('span');
              badge.className = 'scholia-breadcrumb-viewing-badge';
              badge.textContent = ' \u2022 viewing';
              el.appendChild(badge);
            }
          }

          if (entry.link) {
            el.classList.add('scholia-breadcrumb-entry-symlink');
            el.title = 'Symlink \u2192 ' + entry.link;
            var arrow = document.createElement('span');
            arrow.className = 'scholia-breadcrumb-symlink-arrow';
            arrow.textContent = ' \u2197';
            el.appendChild(arrow);
          } else if (entry.name !== '..') {
            el.title = entry.name;
          }

          body.appendChild(el);
        });

        if (data.entries.length === 1 && data.entries[0].name === '..') {
          var empty = document.createElement('div');
          empty.className = 'scholia-breadcrumb-entry';
          empty.style.color = 'var(--s-text-dim)';
          empty.style.fontStyle = 'italic';
          empty.textContent = 'No files';
          body.appendChild(empty);
        }
      })
      .catch(function (err) {
        body.textContent = 'Error: ' + err.message;
      });
  }

  // ── Unified dropdown dismiss (click-outside + Escape) ──

  function closeOptionsMenu() {
    var menu = document.querySelector('.scholia-options-menu');
    if (menu) menu.remove();
  }

  function closeAllDropdowns(except) {
    if (except !== 'breadcrumb') closeBreadcrumbDropdown();
    if (except !== 'toc') closeToc();
    if (except !== 'options') closeOptionsMenu();
  }

  document.addEventListener('click', function (e) {
    // Breadcrumb
    if (activeBreadcrumbDropdown && !activeBreadcrumbDropdown.dropdown.contains(e.target) &&
        !activeBreadcrumbDropdown.seg.contains(e.target)) {
      closeBreadcrumbDropdown();
    }
    // TOC — handled in renderToolbar listener
    // Options
    var optMenu = document.querySelector('.scholia-options-menu');
    var optWrap = document.querySelector('.scholia-options-wrap');
    if (optMenu && optWrap && !optWrap.contains(e.target)) {
      closeOptionsMenu();
    }
  });
  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape') closeAllDropdowns();
  });

  function applyZoom() {
    document.documentElement.style.fontSize = uiZoom + '%';
    positionCards();
  }

  // ── Markdown rendering ─────────────────────────────

  var md = null; // initialized after libs load
  var pandocCache = new Map();   // raw text → Pandoc HTML
  var pandocCallbacks = new Map(); // request_id → callback(html)

  function initMarkdownIt() {
    if (window.markdownit) {
      md = window.markdownit({
        html: false,
        linkify: true,
        typographer: false,
        breaks: true,
      });
      // Add KaTeX math support if texmath plugin loaded
      if (window.texmath && window.katex) {
        md.use(window.texmath, {
          engine: window.katex,
          delimiters: 'dollars',
        });
      }
    }
  }

  function relativeTime(isoString) {
    if (!isoString) return '';
    var then = new Date(isoString);
    var now = new Date();
    var diffMs = now - then;
    var diffSec = Math.floor(diffMs / 1000);
    var diffMin = Math.floor(diffSec / 60);
    var diffHr = Math.floor(diffMin / 60);
    var diffDay = Math.floor(diffHr / 24);

    if (diffSec < 60) return 'just now';
    if (diffMin < 60) return diffMin + ' min ago';
    if (diffHr < 24) return diffHr + (diffHr === 1 ? ' hour ago' : ' hours ago');
    if (diffDay === 1) return 'yesterday';
    if (diffDay < 30) return diffDay + ' days ago';

    var months = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
    var sameYear = then.getFullYear() === now.getFullYear();
    if (sameYear) return months[then.getMonth()] + ' ' + then.getDate();
    return months[then.getMonth()] + ' ' + then.getDate() + ', ' + then.getFullYear();
  }

  // ── Disconnect banner (inserted into toolbar by renderToolbar) ──
  var disconnectBanner = document.createElement('span');
  disconnectBanner.className = 'scholia-disconnect-banner';
  disconnectBanner.textContent = 'Disconnected';
  var disconnectShowTimer = null;

  function showDisconnectBanner() {
    if (disconnectShowTimer) return;  // already pending
    disconnectShowTimer = setTimeout(function () {
      disconnectBanner.classList.add('visible');
      toolbarEl.classList.add('scholia-disconnected');
      disconnectShowTimer = null;
    }, 500);
  }

  function hideDisconnectBanner() {
    if (disconnectShowTimer) {
      clearTimeout(disconnectShowTimer);
      disconnectShowTimer = null;
    }
    disconnectBanner.classList.remove('visible');
    toolbarEl.classList.remove('scholia-disconnected');
  }

  // ── WebSocket ──────────────────────────────────────

  function connectWS() {
    var proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
    ws = new WebSocket(proto + '//' + location.host + '/ws');

    ws.onopen = function () {
      wsAttempt = 0;
      hideDisconnectBanner();
      wsSend({type: 'watch', file: window.__SCHOLIA_DOC_FULLPATH__});
    };

    ws.onmessage = function (e) {
      var msg = JSON.parse(e.data);
      if (msg.type === 'doc_update') {
        if (msg.sidenotes !== undefined) {
          sidenotesEnabled = msg.sidenotes;
          docEl.classList.toggle('scholia-no-sidenotes', !sidenotesEnabled);
          renderToolbar();
        }
        docEl.innerHTML = msg.html;
        buildToc();
        rerenderMath();
        renderMermaid();
        decorateCodeBlocks();
        setupCitationTooltips();
        if (!sidebarHidden) { reanchorAll(); positionCards(); }
      } else if (msg.type === 'comments_update') {
        comments = msg.comments;
        scheduleRender();
        // Refresh overlay if open
        if (activeOverlay) {
          var overlayAnnId = activeOverlay.annotationId;
          for (var ci = 0; ci < comments.length; ci++) {
            if (comments[ci].id === overlayAnnId) {
              closeOverlay();
              openOverlay(comments[ci]);
              break;
            }
          }
        }
      } else if (msg.type === 'rendered_markdown') {
        var cb = pandocCallbacks.get(msg.request_id);
        if (cb) {
          cb(msg.html);
          pandocCallbacks.delete(msg.request_id);
        }
      } else if (msg.type === 'relocated') {
        // File was saved/moved — update paths and UI
        window.__SCHOLIA_DOC_FULLPATH__ = msg.path;
        window.__SCHOLIA_DOC_PATH__ = msg.display_path || msg.path;
        renderToolbar();
        console.log('Scholia: file saved to', msg.path);
      } else if (msg.type === 'error') {
        console.warn('Scholia server error:', msg.message);
        if (msg.message) {
          var errEl = document.createElement('div');
          errEl.style.cssText = 'position:fixed;top:12px;left:50%;transform:translateX(-50%);background:#c0392b;color:#fff;padding:8px 18px;border-radius:6px;z-index:10000;font-size:14px;box-shadow:0 2px 8px rgba(0,0,0,.2)';
          errEl.textContent = msg.message;
          document.body.appendChild(errEl);
          setTimeout(function() { errEl.remove(); }, 5000);
        }
      }
    };

    ws.onerror = function (e) {
      console.warn('Scholia WebSocket error:', e);
    };

    ws.onclose = function () {
      showDisconnectBanner();
      var delay = Math.min(2000 * Math.pow(2, wsAttempt), 30000);
      wsAttempt++;
      setTimeout(connectWS, delay);
    };
  }

  function wsSend(obj) {
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify(obj));
    }
  }

  function showExportWarning(text) {
    var banner = document.createElement('div');
    banner.className = 'scholia-export-warning';
    banner.textContent = text;
    banner.style.cursor = 'pointer';
    banner.addEventListener('click', function () { banner.remove(); });
    document.body.appendChild(banner);
    setTimeout(function () { banner.remove(); }, 8000);
  }

  function isTempFile() {
    var p = window.__SCHOLIA_DOC_FULLPATH__ || '';
    return p.includes('/scholia-') && (p.startsWith('/tmp/') || p.includes('/var/folders/') || p.includes('/T/'));
  }

  function showSaveAsModal() {
    // Compute suggested filename from document title
    var titleEl = document.querySelector('h1');
    var title = (titleEl ? titleEl.textContent : '') || document.title || 'document';
    var slug = title.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '');
    var filename = (slug || 'document') + '.md';

    // Start in ~/Documents if it exists, else home dir
    var homeDir = (window.__SCHOLIA_DOC_FULLPATH__ || '').replace(/\/[^/]+$/, '');
    // Try to guess home dir from full path (e.g. /Users/username/...)
    var homeMatch = (window.__SCHOLIA_DOC_FULLPATH__ || '').match(/^(\/(?:Users|home)\/[^/]+)/);
    var startDir = homeMatch ? homeMatch[1] + '/Documents' : homeDir;

    var currentDir = startDir;

    var overlay = document.createElement('div');
    overlay.className = 'scholia-save-as-overlay';

    var dialog = document.createElement('div');
    dialog.className = 'scholia-save-as-dialog';

    var heading = document.createElement('h3');
    heading.textContent = 'Save as';
    heading.style.margin = '0 0 0.5em 0';
    dialog.appendChild(heading);

    // Current directory display
    var dirLabel = document.createElement('div');
    dirLabel.className = 'scholia-save-as-dir-label';
    dialog.appendChild(dirLabel);

    // Directory browser
    var browser = document.createElement('div');
    browser.className = 'scholia-save-as-browser';
    dialog.appendChild(browser);

    // Filename input row
    var fnRow = document.createElement('div');
    fnRow.style.display = 'flex';
    fnRow.style.gap = '0.5em';
    fnRow.style.alignItems = 'center';
    fnRow.style.marginTop = '0.5em';

    var fnLabel = document.createElement('label');
    fnLabel.textContent = 'Filename:';
    fnLabel.style.fontSize = '0.9em';
    fnLabel.style.whiteSpace = 'nowrap';
    fnRow.appendChild(fnLabel);

    var fnInput = document.createElement('input');
    fnInput.type = 'text';
    fnInput.name = 'save-as-path';
    fnInput.value = filename;
    fnInput.className = 'scholia-save-as-input';
    fnRow.appendChild(fnInput);
    dialog.appendChild(fnRow);

    // Button row
    var btnRow = document.createElement('div');
    btnRow.style.marginTop = '0.75em';
    btnRow.style.display = 'flex';
    btnRow.style.justifyContent = 'flex-end';
    btnRow.style.gap = '0.5em';

    var cancelBtn = document.createElement('button');
    cancelBtn.textContent = 'Cancel';
    cancelBtn.className = 'scholia-save-as-btn';
    cancelBtn.addEventListener('click', function () { overlay.remove(); });

    var saveBtn = document.createElement('button');
    saveBtn.textContent = 'Save';
    saveBtn.className = 'scholia-save-as-btn scholia-save-as-btn-primary';
    saveBtn.addEventListener('click', doSave);

    btnRow.appendChild(cancelBtn);
    btnRow.appendChild(saveBtn);
    dialog.appendChild(btnRow);
    overlay.appendChild(dialog);
    document.body.appendChild(overlay);

    function doSave() {
      var fn = fnInput.value.trim();
      if (!fn) return;
      var dest = currentDir.replace(/\/$/, '') + '/' + fn;
      wsSend({ type: 'save_as', path: dest });
      overlay.remove();
    }

    function loadDir(dirPath) {
      currentDir = dirPath;
      dirLabel.textContent = abbreviatePath(dirPath, 55);
      dirLabel.title = dirPath;
      browser.innerHTML = '';
      var loading = document.createElement('div');
      loading.style.padding = '0.5em';
      loading.style.color = 'var(--s-text-dim, #888)';
      loading.textContent = 'Loading\u2026';
      browser.appendChild(loading);

      fetch('/api/list-dir?path=' + encodeURIComponent(dirPath))
        .then(function (r) { return r.json(); })
        .then(function (data) {
          browser.innerHTML = '';
          if (data.error) {
            // Directory doesn't exist — go to parent
            var parent = dirPath.replace(/\/[^/]+\/?$/, '') || '/';
            if (parent !== dirPath) {
              loadDir(parent);
            } else {
              var errEl = document.createElement('div');
              errEl.style.padding = '0.5em';
              errEl.textContent = data.error;
              browser.appendChild(errEl);
            }
            return;
          }
          currentDir = data.path;
          dirLabel.textContent = abbreviatePath(data.path, 55);
          dirLabel.title = data.path;

          data.entries.forEach(function (entry) {
            if (entry.type !== 'dir' && entry.name !== '..') return; // dirs only
            var row = document.createElement('div');
            row.className = 'scholia-save-as-entry';
            row.textContent = entry.name === '..' ? '\u2190 ..' : entry.name + '/';
            var targetDir = entry.name === '..'
              ? dirPath.replace(/\/$/, '').replace(/\/[^/]+$/, '') || '/'
              : dirPath.replace(/\/$/, '') + '/' + entry.name;
            row.addEventListener('click', function () { loadDir(targetDir); });
            browser.appendChild(row);
          });

          if (data.entries.filter(function (e) { return e.type === 'dir' && e.name !== '..'; }).length === 0) {
            var empty = document.createElement('div');
            empty.className = 'scholia-save-as-entry';
            empty.style.color = 'var(--s-text-dim, #888)';
            empty.style.fontStyle = 'italic';
            empty.textContent = 'No subdirectories';
            browser.appendChild(empty);
          }
        })
        .catch(function (err) {
          browser.innerHTML = '';
          var errEl = document.createElement('div');
          errEl.style.padding = '0.5em';
          errEl.textContent = 'Error: ' + err.message;
          browser.appendChild(errEl);
        });
    }

    loadDir(startDir);

    // Focus filename and select the name portion (before .md)
    fnInput.focus();
    var dotPos = filename.lastIndexOf('.');
    if (dotPos > 0) fnInput.setSelectionRange(0, dotPos);

    // Enter to save
    fnInput.addEventListener('keydown', function (e) {
      if (e.key === 'Enter') doSave();
    });
    // Escape to close
    overlay.addEventListener('keydown', function (e) {
      if (e.key === 'Escape') overlay.remove();
    });
    // Backdrop click to close
    overlay.addEventListener('click', function (e) {
      if (e.target === overlay) overlay.remove();
    });
  }

  // ── Debounced render pipeline ───────────────────────

  var renderRaf = 0;
  function scheduleRender() {
    if (renderRaf) cancelAnimationFrame(renderRaf);
    renderRaf = requestAnimationFrame(function () {
      renderRaf = 0;
      renderSidebar();
      reanchorAll();
      positionCards();
    });
  }

  // ── Toolbar ──────────────────────────────────────────

  // Sidebar toggle icon: panel sliding out (open) or in (closed)
  var commentIcon = '<svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M2 2.5h10a1 1 0 0 1 1 1v6a1 1 0 0 1-1 1H5l-3 2.5v-2.5H2a1 1 0 0 1-1-1v-6a1 1 0 0 1 1-1z"/></svg>';

  function renderToolbar() {
    toolbarEl.innerHTML = '';

    // "scholia on <filename>" at left
    var brandPath = document.createElement('span');
    brandPath.className = 'scholia-toolbar-path';
    var brandLabel = document.createElement('span');
    brandLabel.className = 'scholia-toolbar-path-label';
    var brandLink = document.createElement('a');
    brandLink.className = 'scholia-toolbar-brand';
    brandLink.href = 'https://github.com/postylem/scholia';
    brandLink.target = '_blank';
    brandLink.rel = 'noopener';
    brandLink.textContent = 'scholia';
    brandLabel.appendChild(brandLink);
    brandLabel.appendChild(document.createTextNode(' on '));
    brandPath.appendChild(brandLabel);

    var crumbWrap = document.createElement('span');
    crumbWrap.className = 'scholia-breadcrumb-wrap';
    var docPath = window.__SCHOLIA_DOC_PATH__ || '';
    var docFullPath = window.__SCHOLIA_DOC_FULLPATH__ || docPath;

    // Build breadcrumb segments
    var parts = docPath.split('/').filter(function (p) { return p !== ''; });
    // Compute absolute dir parts from full path
    var fullParts = docFullPath.replace(/\/$/, '').split('/');
    // fullParts ends with filename; dirs are everything before
    for (var si = 0; si < parts.length; si++) {
      var isFile = (si === parts.length - 1);

      // Add "/" separator before all segments except the first
      if (si > 0) {
        var sep = document.createElement('span');
        sep.className = 'scholia-breadcrumb-sep';
        sep.textContent = '/';
        crumbWrap.appendChild(sep);
      }

      var seg = document.createElement('span');
      seg.className = 'scholia-breadcrumb-seg' + (isFile ? ' scholia-breadcrumb-file' : '');
      seg.textContent = parts[si];

      // data-dir = absolute path of the directory whose contents to list
      // This is the parent of the item this segment names
      var fullIdx = fullParts.length - parts.length + si;
      var parentDir = fullParts.slice(0, fullIdx).join('/') || '/';
      seg.setAttribute('data-dir', parentDir);
      seg.setAttribute('data-name', parts[si]);

      seg.addEventListener('click', (function (dirPath, segEl) {
        return function (e) {
          e.stopPropagation();
          openBreadcrumbDropdown(segEl, dirPath);
        };
      })(parentDir, seg));

      crumbWrap.appendChild(seg);
    }
    brandPath.appendChild(crumbWrap);
    toolbarEl.appendChild(brandPath);
    toolbarEl.appendChild(disconnectBanner);

    // Contents (TOC) dropdown — before Options
    tocWrapEl = document.createElement('span');
    tocWrapEl.className = 'scholia-toc-wrap';
    var tocBtn = document.createElement('button');
    tocBtn.className = 'scholia-toolbar-btn';
    tocBtn.title = 'Table of contents';
    tocBtn.innerHTML = '<svg width="12" height="10" viewBox="0 0 12 10" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"><line x1="1" y1="2" x2="8" y2="2"/><line x1="3" y1="5" x2="11" y2="5"/><line x1="3" y1="8" x2="11" y2="8"/></svg>';
    tocBtn.addEventListener('click', function (e) {
      e.stopPropagation();
      toggleToc();
    });
    tocWrapEl.appendChild(tocBtn);
    if (!tocEl) tocWrapEl.style.display = 'none';
    toolbarEl.appendChild(tocWrapEl);
    if (tocEl) {
      tocWrapEl.appendChild(tocEl);
      renderMathIn(tocEl);
    }
    document.addEventListener('click', function closeTocOutside(e) {
      if (tocOpen && tocWrapEl && !tocWrapEl.contains(e.target)) {
        closeToc();
      }
    });

    // Options dropdown
    var optionsWrap = document.createElement('span');
    optionsWrap.className = 'scholia-options-wrap';

    var optionsBtn = document.createElement('button');
    optionsBtn.className = 'scholia-toolbar-btn';
    optionsBtn.textContent = 'Options';
    optionsBtn.addEventListener('click', function (e) {
      e.stopPropagation();
      var menu = optionsWrap.querySelector('.scholia-options-menu');
      if (menu) { menu.remove(); return; }
      closeAllDropdowns('options');
      menu = document.createElement('div');
      menu.className = 'scholia-options-menu';

      var tbl = document.createElement('table');

      // Theme row
      var themeRow = document.createElement('tr');
      var themeTd1 = document.createElement('td');
      themeTd1.textContent = 'Theme';
      themeRow.appendChild(themeTd1);
      var themeTd2 = document.createElement('td');
      var themeGroup = document.createElement('span');
      themeGroup.className = 'scholia-options-toggle';
      var themeModes = ['system', 'light', 'dark'];
      themeModes.forEach(function (mode) {
        var btn = document.createElement('button');
        btn.textContent = mode;
        btn.className = themeMode === mode ? 'active' : '';
        btn.addEventListener('click', function () {
          themeMode = mode;
          localStorage.setItem('scholia-theme', mode);
          if (mode === 'system') {
            darkMode = window.matchMedia('(prefers-color-scheme: dark)').matches;
          } else {
            darkMode = mode === 'dark';
          }
          document.body.classList.toggle('scholia-dark', darkMode);
          menu.remove();
          renderToolbar();
        });
        themeGroup.appendChild(btn);
      });
      themeTd2.appendChild(themeGroup);
      themeRow.appendChild(themeTd2);
      tbl.appendChild(themeRow);

      // Typeface row
      var fontRow = document.createElement('tr');
      var fontTd1 = document.createElement('td');
      fontTd1.textContent = 'Typeface';
      fontRow.appendChild(fontTd1);
      var fontTd2 = document.createElement('td');
      var fontGroup = document.createElement('span');
      fontGroup.className = 'scholia-options-toggle';
      var fontModes = ['default', 'system', 'latex'];
      fontModes.forEach(function (mode) {
        var btn = document.createElement('button');
        btn.textContent = mode;
        btn.className = fontMode === mode ? 'active' : '';
        btn.addEventListener('click', function () {
          document.body.classList.remove('scholia-font-system', 'scholia-font-latex');
          fontMode = mode;
          localStorage.setItem('scholia-font', mode);
          if (mode !== 'default') document.body.classList.add('scholia-font-' + mode);
          menu.remove();
          renderToolbar();
        });
        fontGroup.appendChild(btn);
      });
      fontTd2.appendChild(fontGroup);
      fontRow.appendChild(fontTd2);
      tbl.appendChild(fontRow);

      // Footnote display row
      var fnRow = document.createElement('tr');
      var fnTd1 = document.createElement('td');
      fnTd1.textContent = 'Footnotes';
      fnRow.appendChild(fnTd1);
      var fnTd2 = document.createElement('td');
      var fnGroup = document.createElement('span');
      fnGroup.className = 'scholia-options-toggle';
      var sideBtn = document.createElement('button');
      sideBtn.textContent = 'side';
      sideBtn.className = sidenotesEnabled ? 'active' : '';
      sideBtn.addEventListener('click', function () {
        if (!sidenotesEnabled) {
          sidenotesEnabled = true;
          docEl.classList.remove('scholia-no-sidenotes');
          wsSend({ type: 'toggle_sidenotes', enabled: true });
          menu.remove();
          renderToolbar();
        }
      });
      var endBtn = document.createElement('button');
      endBtn.textContent = 'end';
      endBtn.className = sidenotesEnabled ? '' : 'active';
      endBtn.addEventListener('click', function () {
        if (sidenotesEnabled) {
          sidenotesEnabled = false;
          docEl.classList.add('scholia-no-sidenotes');
          wsSend({ type: 'toggle_sidenotes', enabled: false });
          menu.remove();
          renderToolbar();
        }
      });
      fnGroup.appendChild(sideBtn);
      fnGroup.appendChild(endBtn);
      fnTd2.appendChild(fnGroup);
      fnRow.appendChild(fnTd2);
      tbl.appendChild(fnRow);

      // Zoom row
      var zoomRow = document.createElement('tr');
      var zoomTd1 = document.createElement('td');
      zoomTd1.textContent = 'Zoom';
      zoomRow.appendChild(zoomTd1);
      var zoomTd2 = document.createElement('td');
      var zoomGroup = document.createElement('span');
      zoomGroup.className = 'scholia-options-toggle';
      var zoomMinus = document.createElement('button');
      zoomMinus.textContent = '\u2212';
      zoomMinus.addEventListener('click', function () {
        uiZoom = Math.max(70, uiZoom - 10);
        applyZoom();
        localStorage.setItem('scholia-zoom', uiZoom);
        zoomLabel.textContent = uiZoom + '%';
      });
      var zoomLabel = document.createElement('button');
      zoomLabel.textContent = uiZoom + '%';
      zoomLabel.style.cursor = 'default';
      zoomLabel.style.minWidth = '3em';
      zoomLabel.addEventListener('click', function () {
        uiZoom = 100;
        applyZoom();
        localStorage.setItem('scholia-zoom', uiZoom);
        zoomLabel.textContent = uiZoom + '%';
      });
      var zoomPlus = document.createElement('button');
      zoomPlus.textContent = '+';
      zoomPlus.addEventListener('click', function () {
        uiZoom = Math.min(150, uiZoom + 10);
        applyZoom();
        localStorage.setItem('scholia-zoom', uiZoom);
        zoomLabel.textContent = uiZoom + '%';
      });
      zoomGroup.appendChild(zoomMinus);
      zoomGroup.appendChild(zoomLabel);
      zoomGroup.appendChild(zoomPlus);
      zoomTd2.appendChild(zoomGroup);
      zoomRow.appendChild(zoomTd2);
      tbl.appendChild(zoomRow);

      // Save as row (only for temp files)
      if (isTempFile()) {
        var saveAsRow = document.createElement('tr');
        saveAsRow.className = 'scholia-export-row scholia-save-as-row';
        var saveAsTd = document.createElement('td');
        saveAsTd.setAttribute('colspan', '2');
        var saveAsBtn = document.createElement('button');
        saveAsBtn.className = 'scholia-export-btn';
        saveAsBtn.textContent = 'Save as\u2026';
        saveAsBtn.addEventListener('click', function () {
          menu.remove();
          showSaveAsModal();
        });
        saveAsTd.appendChild(saveAsBtn);
        saveAsRow.appendChild(saveAsTd);
        tbl.appendChild(saveAsRow);
      }

      // Export PDF row (separator + button, visually distinct from toggles)
      var exportRow = document.createElement('tr');
      exportRow.className = 'scholia-export-row';
      var exportTd = document.createElement('td');
      exportTd.setAttribute('colspan', '2');
      var exportBtn = document.createElement('button');
      exportBtn.className = 'scholia-export-btn';
      exportBtn.textContent = 'Export PDF';
      exportBtn.addEventListener('click', function () {
        exportBtn.textContent = 'Exporting\u2026';
        exportBtn.disabled = true;
        var fileParam = encodeURIComponent(window.__SCHOLIA_DOC_FULLPATH__ || '');
        fetch('/api/export-pdf?file=' + fileParam)
          .then(function (resp) {
            if (resp.ok) {
              return resp.blob().then(function (blob) {
                var url = URL.createObjectURL(blob);
                var a = document.createElement('a');
                a.href = url;
                var name = (window.__SCHOLIA_DOC_PATH__ || 'document').split('/').pop();
                a.download = name.replace(/\.[^.]+$/, '') + '.pdf';
                document.body.appendChild(a);
                a.click();
                document.body.removeChild(a);
                URL.revokeObjectURL(url);
                menu.remove();
              });
            } else {
              return resp.json().then(function (data) {
                menu.remove();
                if (data.fallback === 'print') {
                  showExportWarning('PDF export requires a LaTeX engine. Using browser print instead.');
                  setTimeout(function () { window.print(); }, 300);
                } else {
                  showExportWarning('Export failed: ' + (data.error || 'unknown error'));
                }
              });
            }
          })
          .catch(function (err) {
            menu.remove();
            showExportWarning('Export failed: ' + err.message);
          });
      });
      exportTd.appendChild(exportBtn);
      exportRow.appendChild(exportTd);
      tbl.appendChild(exportRow);

      // Stop server row
      var stopRow = document.createElement('tr');
      stopRow.className = 'scholia-export-row';
      var stopTd = document.createElement('td');
      stopTd.setAttribute('colspan', '2');
      var stopBtn = document.createElement('button');
      stopBtn.className = 'scholia-export-btn';
      stopBtn.textContent = 'Stop server';
      stopBtn.addEventListener('click', function () {
        stopBtn.disabled = true;
        stopBtn.textContent = 'Stopping\u2026';
        menu.remove();
        fetch('/api/shutdown', { method: 'POST' }).catch(function () {});
      });
      stopTd.appendChild(stopBtn);
      stopRow.appendChild(stopTd);
      tbl.appendChild(stopRow);

      menu.appendChild(tbl);

      optionsWrap.appendChild(menu);
    });
    optionsWrap.appendChild(optionsBtn);
    toolbarEl.appendChild(optionsWrap);

    var btnGroup = document.createElement('span');
    btnGroup.className = 'scholia-toolbar-group';

    if (!sidebarHidden) {
      var resolvedBtn = document.createElement('button');
      resolvedBtn.className = 'scholia-toolbar-btn' + (showResolved ? ' active' : '');
      resolvedBtn.textContent = 'Resolved';
      resolvedBtn.title = showResolved ? 'Hide resolved threads' : 'Show resolved threads';
      resolvedBtn.addEventListener('click', function () {
        showResolved = !showResolved;
        renderToolbar();
        scheduleRender();
      });
      btnGroup.appendChild(resolvedBtn);

      var readBtn = document.createElement('button');
      readBtn.className = 'scholia-toolbar-btn' + (showRead ? ' active' : '');
      readBtn.textContent = 'Read';
      readBtn.title = showRead ? 'Hide read threads' : 'Show read threads';
      readBtn.addEventListener('click', function () {
        showRead = !showRead;
        renderToolbar();
        scheduleRender();
      });
      btnGroup.appendChild(readBtn);
    }

    var cbBtn = document.createElement('button');
    cbBtn.className = 'scholia-toolbar-btn' + (!sidebarHidden ? ' active' : '');
    cbBtn.innerHTML = commentIcon;
    cbBtn.title = !sidebarHidden ? 'Hide comments' : 'Show comments';
    cbBtn.addEventListener('click', function () {
      if (sidebarHidden) {
        sidebarHidden = false;
        containerEl.classList.remove('scholia-sidebar-hidden');
        scheduleRender();
        // Reposition after grid transition completes
        containerEl.addEventListener('transitionend', function handler(e) {
          if (e.propertyName === 'grid-template-columns') {
            containerEl.removeEventListener('transitionend', handler);
            positionCards();
          }
        });
      } else {
        sidebarHidden = true;
        containerEl.classList.add('scholia-sidebar-hidden');
        clearAllHighlights();
        dismissCommentPrompt();
      }
      renderToolbar();
    });
    btnGroup.appendChild(cbBtn);

    toolbarEl.appendChild(btnGroup);
  }

  function clearAllHighlights() {
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
  }

  // ── Math rendering ─────────────────────────────────

  function renderMathIn(container) {
    if (!window.katex) return;
    // Pandoc --katex outputs <span class="math inline"> and <span class="math display">
    var mathEls = container.querySelectorAll('span.math:not(.scholia-math-rendered)');
    for (var i = 0; i < mathEls.length; i++) {
      var el = mathEls[i];
      var displayMode = el.classList.contains('display');
      el.dataset.latex = el.textContent;
      try {
        katex.render(el.textContent, el, { displayMode: displayMode, throwOnError: false });
        el.classList.add('scholia-math-rendered');
      } catch (e) {
        // leave raw LaTeX visible on error
      }
    }
  }

  function rerenderMath() {
    renderMathIn(docEl);
  }

  function renderMermaid() {
    if (!window.mermaid) return;
    var pres = docEl.querySelectorAll('pre.mermaid');
    if (pres.length === 0) return;
    window.mermaid.run({ nodes: pres });
  }

  function postProcessPandocHtml(container) {
    renderMathIn(container);
    setupCitationTooltipsIn(container);
  }

  // ── Table of contents & collapsible sections ────────

  var tocEl = null;
  var tocWrapEl = null;
  var tocOpen = false;

  function buildToc() {
    // Remove old TOC dropdown content
    if (tocEl) tocEl.remove();
    tocEl = null;

    var headings = docEl.querySelectorAll('h1, h2, h3, h4');
    var items = [];
    for (var i = 0; i < headings.length; i++) {
      var h = headings[i];
      if (h.closest('#title-block-header')) continue;
      var section = h.parentElement;
      if (!section || section.tagName !== 'SECTION') continue;
      var level = parseInt(h.tagName[1]);
      items.push({ heading: h, section: section, level: level, id: section.id || h.id || '' });
    }
    if (items.length === 0) {
      if (tocWrapEl) tocWrapEl.style.display = 'none';
      return;
    }
    if (tocWrapEl) tocWrapEl.style.display = '';

    // Clean heading HTML for ToC: flatten citations to text, keep math spans
    function tocHTML(heading) {
      var tmp = document.createElement('span');
      tmp.innerHTML = heading.innerHTML;
      var cites = tmp.querySelectorAll('.citation');
      for (var i = 0; i < cites.length; i++) {
        cites[i].replaceWith(document.createTextNode(cites[i].textContent));
      }
      return tmp.innerHTML;
    }

    tocEl = document.createElement('div');
    tocEl.className = 'scholia-toc';

    var body = document.createElement('div');
    body.className = 'scholia-toc-body';

    // Build nested list
    var root = document.createElement('ul');
    var stack = [{ ul: root, level: 0 }];

    for (var j = 0; j < items.length; j++) {
      var item = items[j];
      while (stack.length > 1 && stack[stack.length - 1].level >= item.level) {
        stack.pop();
      }
      // Ensure proper nesting depth even if heading levels skip (e.g. h2 before any h1)
      while (item.level > stack[stack.length - 1].level + 1) {
        var wrapLi = document.createElement('li');
        var wrapUl = document.createElement('ul');
        wrapLi.appendChild(wrapUl);
        stack[stack.length - 1].ul.appendChild(wrapLi);
        stack.push({ ul: wrapUl, level: stack[stack.length - 1].level + 1 });
      }
      var parentUl = stack[stack.length - 1].ul;
      var hasChildren = (j + 1 < items.length && items[j + 1].level > item.level);

      var li = document.createElement('li');
      if (hasChildren) {
        var startCollapsed = item.level >= 3;
        li.className = 'scholia-toc-branch' + (startCollapsed ? ' collapsed' : '');
        var chevron = document.createElement('span');
        chevron.className = 'scholia-toc-chevron';
        chevron.textContent = startCollapsed ? '+' : '\u2212';
        chevron.addEventListener('click', (function (theLi, theChevron) {
          return function (e) {
            e.stopPropagation();
            theLi.classList.toggle('collapsed');
            theChevron.textContent = theLi.classList.contains('collapsed') ? '+' : '\u2212';
          };
        })(li, chevron));
        li.appendChild(chevron);
        var a = document.createElement('a');
        a.href = '#' + item.id;
        a.className = 'scholia-toc-h' + item.level;
        a.innerHTML = tocHTML(item.heading);
        a.dataset.sectionId = item.id;
        a.addEventListener('click', tocClickHandler);
        li.appendChild(a);
        var childUl = document.createElement('ul');
        li.appendChild(childUl);
        stack.push({ ul: childUl, level: item.level });
      } else {
        var spacer = document.createElement('span');
        spacer.className = 'scholia-toc-spacer';
        li.appendChild(spacer);
        var a = document.createElement('a');
        a.href = '#' + item.id;
        a.className = 'scholia-toc-h' + item.level;
        a.innerHTML = tocHTML(item.heading);
        a.dataset.sectionId = item.id;
        a.addEventListener('click', tocClickHandler);
        li.appendChild(a);
      }
      parentUl.appendChild(li);
    }

    body.appendChild(root);
    tocEl.appendChild(body);

    // Insert into the toolbar wrap (created in renderToolbar)
    if (tocWrapEl) {
      tocWrapEl.appendChild(tocEl);
      renderMathIn(tocEl);
    }

    // Set up collapsible sections
    setupCollapsibleSections();

    // Highlight active section on scroll
    window.removeEventListener('scroll', updateTocActive);
    window.addEventListener('scroll', updateTocActive, { passive: true });
  }

  function toggleToc() {
    if (tocOpen) { closeToc(); return; }
    closeAllDropdowns();
    tocOpen = true;
    if (tocEl) tocEl.classList.add('scholia-toc-open');
  }

  function closeToc() {
    tocOpen = false;
    if (tocEl) tocEl.classList.remove('scholia-toc-open');
  }

  function tocClickHandler(e) {
    e.preventDefault();
    var target = document.getElementById(this.dataset.sectionId);
    if (target) {
      var section = target.tagName === 'SECTION' ? target : target.closest('section');
      if (section) uncollapseAncestors(section);
      closeToc();
      target.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
  }

  function uncollapseAncestors(el) {
    var node = el;
    while (node && node !== docEl) {
      if (node.tagName === 'SECTION' && node.classList.contains('scholia-collapsed')) {
        node.classList.remove('scholia-collapsed');
      }
      node = node.parentElement;
    }
  }

  function setupCollapsibleSections() {
    var sections = docEl.querySelectorAll('section');
    for (var i = 0; i < sections.length; i++) {
      var sec = sections[i];
      var heading = sec.querySelector(':scope > h1, :scope > h2, :scope > h3, :scope > h4');
      if (!heading) continue;
      if (heading.closest('#title-block-header')) continue;
      // Skip if already has listener (re-render)
      if (heading.dataset.collapsible) continue;
      heading.dataset.collapsible = 'true';
      heading.addEventListener('click', (function (theSec) {
        return function () {
          theSec.classList.toggle('scholia-collapsed');
        };
      })(sec));
    }
  }

  var tocActiveLink = null;
  function updateTocActive() {
    if (!tocEl) return;
    var links = tocEl.querySelectorAll('a[data-section-id]');
    var current = null;
    for (var i = 0; i < links.length; i++) {
      var target = document.getElementById(links[i].dataset.sectionId);
      if (target && target.getBoundingClientRect().top <= 80) {
        current = links[i];
      }
    }
    if (current !== tocActiveLink) {
      if (tocActiveLink) tocActiveLink.classList.remove('scholia-toc-active');
      if (current) current.classList.add('scholia-toc-active');
      tocActiveLink = current;
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
    if (md) {
      return md.render(text);
    }
    // Fallback: escape HTML and preserve whitespace (original minimal behavior)
    return '<p>' + escapeHtml(text) + '</p>';
  }

  function rerenderCommentBodies() {
    if (!md) return;
    var bodies = sidebarEl.querySelectorAll('.scholia-message-body');
    for (var i = 0; i < bodies.length; i++) {
      var raw = bodies[i].dataset.raw;
      if (raw !== undefined) bodies[i].innerHTML = renderCommentBody(raw);
    }
  }

  // ── Per-user color ───────────────────────────────────

  var userColorCache = {};

  function userColor(name, creatorType) {
    if (creatorType === 'Software') return 'var(--s-ai)';
    if (userColorCache[name]) return userColorCache[name];
    // djb2 hash → hue
    var hash = 5381;
    for (var i = 0; i < name.length; i++) {
      hash = ((hash << 5) + hash + name.charCodeAt(i)) & 0x7fffffff;
    }
    var hue = hash % 360;
    // Keep saturation/lightness in a readable range
    var color = 'hsl(' + hue + ', 55%, 38%)';
    userColorCache[name] = color;
    return color;
  }

  // ── Auto-grow textarea ──────────────────────────────

  function autoGrow(textarea, maxHeight) {
    maxHeight = maxHeight || 150;
    textarea.addEventListener('input', function () {
      textarea.style.height = 'auto';
      textarea.style.height = Math.min(textarea.scrollHeight, maxHeight) + 'px';
      positionCards();
    });
  }

  // ── Unread detection ───────────────────────────────

  function isUnread(ann) {
    var bodies = ann.body || [];
    if (bodies.length === 0) return false;

    // If the last message is by a human (not Software), they've seen everything
    var lastBody = bodies[bodies.length - 1];
    if (!(lastBody.creator && lastBody.creator.type === 'Software')) return false;

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

  // ── Read/unread helpers ──────────────────────────────

  function markRead(annId, card) {
    wsSend({ type: 'mark_read', annotation_id: annId });
    state[annId] = { lastReadAt: new Date().toISOString() };
    if (card) {
      card.classList.remove('scholia-unread');
      var dot = card.querySelector('.scholia-unread-dot');
      if (dot) dot.remove();
    }
  }

  function markUnread(annId) {
    wsSend({ type: 'mark_unread', annotation_id: annId });
    state[annId] = { lastReadAt: null };
    renderSidebar();
    positionCards();
  }

  // ── Sidebar ────────────────────────────────────────

  function renderSidebar() {
    if (readonlyMode) { sidebarEl.innerHTML = ''; return; }
    // Preserve any open new-comment form
    var existingForm = document.getElementById('scholia-new-comment');

    sidebarEl.innerHTML = '';

    if (existingForm) {
      sidebarEl.appendChild(existingForm);
    }

    // Filter comments
    var filtered = [];
    for (var i = 0; i < comments.length; i++) {
      var ann = comments[i];
      var status = ann['scholia:status'] || 'open';
      if (!showResolved && status === 'resolved') continue;
      if (!showRead && !isUnread(ann)) continue;
      filtered.push(ann);
    }

    if (filtered.length === 0) {
      var empty = document.createElement('div');
      empty.className = 'scholia-empty';
      var reason = !showResolved && !showRead
        ? 'No unread open comments.'
        : !showResolved
          ? 'No open comments.'
          : !showRead
            ? 'No unresolved unread comments.'
            : 'No comments yet.';
      empty.textContent = reason + ' Select text to add one.';
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
      if (bodies[b].creator && bodies[b].creator.type === 'Software') {
        hasAiReply = true;
        break;
      }
    }
    if (hasAiReply) card.classList.add('scholia-ai-replied');

    // Unread detection (timestamp-based)
    var unread = isUnread(ann);
    if (unread) card.classList.add('scholia-unread');

    // Track last AI message index for placing mark-unread button
    var lastAiIdx = -1;
    for (var b2 = bodies.length - 1; b2 >= 0; b2--) {
      if (bodies[b2].creator && bodies[b2].creator.type === 'Software') {
        lastAiIdx = b2;
        break;
      }
    }

    // Header
    var header = document.createElement('div');
    header.className = 'scholia-card-header';

    var anchorText = (ann.target && ann.target['scholia:sourceSelector'] && ann.target['scholia:sourceSelector'].exact)
      || (ann.target && ann.target.selector && ann.target.selector.exact) || '(no anchor)';
    var anchorSpan = document.createElement('span');
    anchorSpan.className = 'scholia-anchor-text';
    var openQ = document.createElement('span');
    openQ.className = 'scholia-anchor-quote';
    openQ.textContent = '\u201c';
    var closeQ = document.createElement('span');
    closeQ.className = 'scholia-anchor-quote';
    closeQ.textContent = (anchorText.length > 50 ? '\u2026' : '') + '\u201d';
    anchorSpan.appendChild(openQ);
    anchorSpan.appendChild(document.createTextNode(anchorText.slice(0, 50)));
    anchorSpan.appendChild(closeQ);
    if (anchorText.length > 50) anchorSpan.title = anchorText;
    header.appendChild(anchorSpan);

    // Orphan icon
    if (orphanIds.has(ann.id)) {
      var orphanIcon = document.createElement('span');
      orphanIcon.className = 'scholia-orphan-icon';
      orphanIcon.textContent = '?';
      var orphanTip = document.createElement('div');
      orphanTip.className = 'scholia-orphan-tooltip';
      orphanTip.textContent = 'Anchor text not found. Click to re-anchor.';
      orphanIcon.appendChild(orphanTip);
      orphanIcon.addEventListener('click', (function (theAnnId) {
        return function (e) {
          e.stopPropagation();
          startReanchor(theAnnId);
        };
      })(ann.id));
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

    // Unread dot
    if (unread) {
      var dot = document.createElement('span');
      dot.className = 'scholia-unread-dot';
      header.appendChild(dot);
    }

    // Pop-out button
    var popoutBtn = document.createElement('button');
    popoutBtn.className = 'scholia-btn-popout';
    popoutBtn.innerHTML = '&#x2922;'; // ⤢
    popoutBtn.title = 'Pop out thread';
    popoutBtn.addEventListener('click', (function (theAnn) {
      return function (e) {
        e.stopPropagation();
        openOverlay(theAnn);
      };
    })(ann));
    header.appendChild(popoutBtn);

    card.appendChild(header);

    // Thread (collapsed)
    var thread = document.createElement('div');
    thread.className = 'scholia-thread';
    thread.style.display = 'none';

    for (var j = 0; j < bodies.length; j++) {
      var msg = bodies[j];
      var msgEl = document.createElement('div');
      var msgCreator = (msg.creator && msg.creator.name) || 'unknown';
      var isSoftware = msg.creator && msg.creator.type === 'Software';
      var role = isSoftware ? 'ai' : 'human';
      msgEl.className = 'scholia-message scholia-' + role;

      var meta = document.createElement('div');
      meta.className = 'scholia-message-meta';
      if (isSoftware && msg.creator.nickname) {
        var authorSpan = document.createElement('span');
        authorSpan.className = 'scholia-author-label';
        authorSpan.textContent = msgCreator + ' ';
        var modelSpan = document.createElement('span');
        modelSpan.className = 'scholia-model-name';
        modelSpan.textContent = msg.creator.nickname;
        authorSpan.appendChild(modelSpan);
        meta.appendChild(authorSpan);
      } else {
        meta.textContent = msgCreator;
      }
      meta.style.color = userColor(msgCreator, msg.creator && msg.creator.type);

      // Relative timestamp
      var timeSpan = document.createElement('span');
      timeSpan.className = 'scholia-message-time';
      timeSpan.textContent = relativeTime(msg.created);
      if (msg.created) timeSpan.title = new Date(msg.created).toLocaleString();
      meta.appendChild(timeSpan);

      msgEl.appendChild(meta);

      var body = document.createElement('div');
      body.className = 'scholia-message-body';
      body.dataset.raw = msg.value;
      body.innerHTML = renderCommentBody(msg.value);
      msgEl.appendChild(body);

      // Raw/rendered toggle button
      var toggleBtn = document.createElement('button');
      toggleBtn.className = 'scholia-btn-toggle-raw';
      toggleBtn.textContent = '</>';
      toggleBtn.title = 'Toggle raw markdown';
      toggleBtn.addEventListener('click', (function (theBody, theBtn) {
        return function (e) {
          e.stopPropagation();
          if (theBody.classList.contains('scholia-raw-view')) {
            // Switch back to rendered
            theBody.classList.remove('scholia-raw-view');
            theBody.innerHTML = renderCommentBody(theBody.dataset.raw);
            theBtn.classList.remove('active');
          } else {
            // Switch to raw
            theBody.classList.add('scholia-raw-view');
            theBody.textContent = theBody.dataset.raw;
            theBtn.classList.add('active');
          }
        };
      })(body, toggleBtn));
      meta.appendChild(toggleBtn);

      // Edit button on the very last body entry, only if it's the current user's message
      if (j === bodies.length - 1 && !isSoftware && msgCreator === creatorName) {
        var editBtn = document.createElement('button');
        editBtn.className = 'scholia-btn-edit';
        editBtn.textContent = 'Edit';
        editBtn.addEventListener('click', (function (theBody, theAnn) {
          return function (e) {
            e.stopPropagation();
            var raw = theBody.dataset.raw;
            var ta = document.createElement('textarea');
            ta.name = 'edit-' + theAnn.id;
            ta.className = 'scholia-edit-textarea';
            ta.value = raw;
            ta.rows = Math.max(2, raw.split('\n').length);
            autoGrow(ta);
            theBody.innerHTML = '';
            theBody.appendChild(ta);
            ta.focus();

            var btnRow = document.createElement('div');
            btnRow.className = 'scholia-edit-buttons';

            var saveBtn = document.createElement('button');
            saveBtn.textContent = 'Save';
            saveBtn.addEventListener('click', function (ev) {
              ev.stopPropagation();
              var newText = ta.value.trim();
              if (newText && newText !== raw) {
                wsSend({
                  type: 'edit_body',
                  annotation_id: theAnn.id,
                  body: newText
                });
              } else {
                // Revert if empty or unchanged
                theBody.innerHTML = renderCommentBody(raw);
                theBody.dataset.raw = raw;
              }
            });
            btnRow.appendChild(saveBtn);

            var cancelBtn = document.createElement('button');
            cancelBtn.textContent = 'Cancel';
            cancelBtn.addEventListener('click', function (ev) {
              ev.stopPropagation();
              theBody.innerHTML = renderCommentBody(raw);
              theBody.dataset.raw = raw;
            });
            btnRow.appendChild(cancelBtn);

            var editPreviewDiv = null;
            var editPreviewBtn = document.createElement('button');
            editPreviewBtn.className = 'scholia-btn-ghost';
            editPreviewBtn.textContent = 'Preview';
            editPreviewBtn.addEventListener('click', function (ev) {
              ev.stopPropagation();
              if (editPreviewDiv) {
                editPreviewDiv.remove();
                editPreviewDiv = null;
                ta.style.display = '';
                editPreviewBtn.textContent = 'Preview';
              } else {
                editPreviewDiv = document.createElement('div');
                editPreviewDiv.className = 'scholia-message-body scholia-preview-body';
                editPreviewDiv.innerHTML = renderCommentBody(ta.value);
                ta.style.display = 'none';
                theBody.insertBefore(editPreviewDiv, btnRow);
                editPreviewBtn.textContent = 'Edit';
              }
            });
            btnRow.appendChild(editPreviewBtn);

            theBody.appendChild(btnRow);
          };
        })(body, ann));
        meta.appendChild(editBtn);
      }

      // Last AI message: read/unread toggle label in upper-right
      if (j === lastAiIdx) {
        var readLabel = document.createElement('button');
        readLabel.className = 'scholia-read-toggle';
        if (unread) {
          readLabel.classList.add('scholia-read-toggle-unread');
          readLabel.textContent = 'unread';
        } else {
          readLabel.textContent = 'mark unread';
        }
        readLabel.addEventListener('click', (function (theCard, theLabel) {
          return function (e) {
            e.stopPropagation();
            if (theLabel.classList.contains('scholia-read-toggle-unread')) {
              // Dismiss: mark read
              markRead(ann.id, theCard);
              theLabel.classList.remove('scholia-read-toggle-unread');
              theLabel.textContent = 'mark unread';
            } else {
              // Re-mark as unread
              markUnread(ann.id);
            }
          };
        })(card, readLabel));
        // Insert into meta row (upper-right)
        meta.appendChild(readLabel);
      }

      thread.appendChild(msgEl);
    }

    // Reply input
    var replyRow = document.createElement('div');
    replyRow.className = 'scholia-reply-input';

    var replyTextarea = document.createElement('textarea');
    replyTextarea.name = 'reply-' + ann.id;
    replyTextarea.placeholder = 'Reply\u2026';
    replyTextarea.rows = 1;
    autoGrow(replyTextarea);
    // Focusing the reply also marks as read
    replyTextarea.addEventListener('focus', (function (theCard) {
      return function () {
        if (isUnread(ann)) {
          markRead(ann.id, theCard);
          var label = thread.querySelector('.scholia-read-toggle-unread');
          if (label) {
            label.classList.remove('scholia-read-toggle-unread');
            label.textContent = 'mark unread';
          }
        }
      };
    })(card));
    replyRow.appendChild(replyTextarea);

    var replyBtnRow = document.createElement('div');
    replyBtnRow.className = 'scholia-reply-buttons';

    var replyBtn = document.createElement('button');
    replyBtn.className = 'scholia-btn-primary';
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
    replyBtnRow.appendChild(replyBtn);

    // Preview button for sidebar reply
    var sidebarPreviewDiv = null;
    var sidebarPreviewBtn = document.createElement('button');
    sidebarPreviewBtn.className = 'scholia-btn-ghost';
    sidebarPreviewBtn.textContent = 'Preview';
    sidebarPreviewBtn.addEventListener('click', (function (ta, row) {
      return function () {
        if (sidebarPreviewDiv) {
          sidebarPreviewDiv.remove();
          sidebarPreviewDiv = null;
          ta.style.display = '';
          sidebarPreviewBtn.textContent = 'Preview';
        } else {
          sidebarPreviewDiv = document.createElement('div');
          sidebarPreviewDiv.className = 'scholia-message-body scholia-preview-body';
          sidebarPreviewDiv.innerHTML = renderCommentBody(ta.value);
          ta.style.display = 'none';
          row.insertBefore(sidebarPreviewDiv, replyBtnRow);
          sidebarPreviewBtn.textContent = 'Edit';
          // Keep bottom visible
          var thr = row.closest('.scholia-thread');
          if (thr) thr.scrollTop = thr.scrollHeight;
        }
      };
    })(replyTextarea, replyRow));
    replyBtnRow.appendChild(sidebarPreviewBtn);

    // Resolve/unresolve button in the reply row
    if (status === 'open') {
      var resolveBtn = document.createElement('button');
      resolveBtn.className = 'scholia-btn-ghost';
      resolveBtn.textContent = 'Resolve';
      resolveBtn.addEventListener('click', function (e) {
        e.stopPropagation();
        wsSend({ type: 'resolve', annotation_id: ann.id });
        markRead(ann.id, card);
      });
      replyBtnRow.appendChild(resolveBtn);
    } else if (status === 'resolved') {
      var unresolveBtn = document.createElement('button');
      unresolveBtn.className = 'scholia-btn-ghost';
      unresolveBtn.textContent = 'Unresolve';
      unresolveBtn.addEventListener('click', function (e) {
        e.stopPropagation();
        wsSend({ type: 'unresolve', annotation_id: ann.id });
      });
      replyBtnRow.appendChild(unresolveBtn);
    }

    replyRow.appendChild(replyBtnRow);
    thread.appendChild(replyRow);

    card.appendChild(thread);

    // Click header to expand/collapse
    header.addEventListener('click', function () {
      var wasExpanded = card.classList.contains('scholia-expanded');
      expandOverrides[ann.id] = !wasExpanded;

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

  // ── Pop-out overlay ──────────────────────────────────

  var activeOverlay = null;  // track currently open overlay

  function openOverlay(ann) {
    if (activeOverlay) closeOverlay();

    var backdrop = document.createElement('div');
    backdrop.className = 'scholia-overlay-backdrop';
    backdrop.addEventListener('click', closeOverlay);

    var panel = document.createElement('div');
    panel.className = 'scholia-overlay-panel';
    panel.addEventListener('click', function (e) { e.stopPropagation(); });

    // Header
    var hdr = document.createElement('div');
    hdr.className = 'scholia-overlay-header';

    var anchorText = (ann.target && ann.target['scholia:sourceSelector'] && ann.target['scholia:sourceSelector'].exact)
      || (ann.target && ann.target.selector && ann.target.selector.exact) || '(no anchor)';
    var hdrText = document.createElement('span');
    hdrText.className = 'scholia-overlay-anchor';
    var oOpenQ = document.createElement('span');
    oOpenQ.className = 'scholia-anchor-quote';
    oOpenQ.textContent = '\u201c';
    var oCloseQ = document.createElement('span');
    oCloseQ.className = 'scholia-anchor-quote';
    oCloseQ.textContent = (anchorText.length > 80 ? '\u2026' : '') + '\u201d';
    hdrText.appendChild(oOpenQ);
    hdrText.appendChild(document.createTextNode(anchorText.slice(0, 80)));
    hdrText.appendChild(oCloseQ);
    hdr.appendChild(hdrText);

    var hdrRight = document.createElement('span');
    hdrRight.className = 'scholia-overlay-header-right';

    var countLabel = document.createElement('span');
    countLabel.className = 'scholia-overlay-count';
    var bodies = ann.body || [];
    countLabel.textContent = bodies.length + (bodies.length === 1 ? ' message' : ' messages');
    hdrRight.appendChild(countLabel);

    // Pandoc toggle for whole overlay (on by default)
    var overlayPandocActive = true;
    var overlayBodies = []; // collect body elements for bulk toggle
    var pandocHeaderBtn = document.createElement('button');
    pandocHeaderBtn.className = 'scholia-btn-pandoc active';
    pandocHeaderBtn.textContent = 'P';
    pandocHeaderBtn.title = 'Render citations via Pandoc — click to toggle off';
    pandocHeaderBtn.addEventListener('click', function (e) {
      e.stopPropagation();
      overlayPandocActive = !overlayPandocActive;
      pandocHeaderBtn.classList.toggle('active', overlayPandocActive);
      pandocHeaderBtn.title = overlayPandocActive
        ? 'Render citations via Pandoc — click to toggle off'
        : 'Citations off — click to render via Pandoc';
      for (var bi = 0; bi < overlayBodies.length; bi++) {
        var b = overlayBodies[bi];
        if (b.classList.contains('scholia-raw-view')) continue; // skip if in raw mode
        var raw = b.dataset.raw;
        if (overlayPandocActive) {
          if (pandocCache.has(raw)) {
            b.innerHTML = pandocCache.get(raw);
            postProcessPandocHtml(b);
          }
          // else already requested or will be requested
        } else {
          b.innerHTML = renderCommentBody(raw);
        }
      }
    });
    hdrRight.appendChild(pandocHeaderBtn);

    var closeBtn = document.createElement('button');
    closeBtn.className = 'scholia-btn-ghost';
    closeBtn.innerHTML = '&#x2715; Close';
    closeBtn.addEventListener('click', closeOverlay);
    hdrRight.appendChild(closeBtn);

    hdr.appendChild(hdrRight);
    panel.appendChild(hdr);

    // Thread body
    var threadBody = document.createElement('div');
    threadBody.className = 'scholia-overlay-thread';

    for (var j = 0; j < bodies.length; j++) {
      var msg = bodies[j];
      var msgEl = document.createElement('div');
      var isSoftware = msg.creator && msg.creator.type === 'Software';
      var role = isSoftware ? 'ai' : 'human';
      msgEl.className = 'scholia-overlay-message scholia-' + role;

      var meta = document.createElement('div');
      meta.className = 'scholia-overlay-message-meta';
      var msgCreator = (msg.creator && msg.creator.name) || 'unknown';

      var authorSpan = document.createElement('span');
      authorSpan.style.color = userColor(msgCreator, msg.creator && msg.creator.type);
      if (isSoftware && msg.creator.nickname) {
        authorSpan.className = 'scholia-author-label';
        authorSpan.textContent = msgCreator + ' ';
        var modelSpan = document.createElement('span');
        modelSpan.className = 'scholia-model-name';
        modelSpan.textContent = msg.creator.nickname;
        authorSpan.appendChild(modelSpan);
      } else {
        authorSpan.textContent = msgCreator;
      }
      meta.appendChild(authorSpan);

      var timeSpan = document.createElement('span');
      timeSpan.className = 'scholia-message-time';
      timeSpan.textContent = relativeTime(msg.created);
      if (msg.created) timeSpan.title = new Date(msg.created).toLocaleString();
      meta.appendChild(timeSpan);

      var bodyEl = document.createElement('div');
      bodyEl.className = 'scholia-message-body';
      bodyEl.dataset.raw = msg.value;
      bodyEl.innerHTML = renderCommentBody(msg.value);
      overlayBodies.push(bodyEl);

      var toggleBtn = document.createElement('button');
      toggleBtn.className = 'scholia-btn-toggle-raw';
      toggleBtn.textContent = '</>';
      toggleBtn.title = 'Toggle raw markdown';
      toggleBtn.addEventListener('click', (function (theBody, theBtn) {
        return function (e) {
          e.stopPropagation();
          if (theBody.classList.contains('scholia-raw-view')) {
            theBody.classList.remove('scholia-raw-view');
            // Restore to Pandoc or markdown-it depending on overlay state
            var raw = theBody.dataset.raw;
            if (overlayPandocActive && pandocCache.has(raw)) {
              theBody.innerHTML = pandocCache.get(raw);
              postProcessPandocHtml(theBody);
            } else {
              theBody.innerHTML = renderCommentBody(raw);
            }
            theBtn.classList.remove('active');
          } else {
            theBody.classList.add('scholia-raw-view');
            theBody.textContent = theBody.dataset.raw;
            theBtn.classList.add('active');
          }
        };
      })(bodyEl, toggleBtn));
      meta.appendChild(toggleBtn);

      msgEl.appendChild(meta);
      msgEl.appendChild(bodyEl);
      threadBody.appendChild(msgEl);
    }
    panel.appendChild(threadBody);

    // Reply row
    var replyRow = document.createElement('div');
    replyRow.className = 'scholia-overlay-reply';

    var replyTextarea = document.createElement('textarea');
    replyTextarea.name = 'overlay-reply-' + ann.id;
    replyTextarea.placeholder = 'Reply\u2026';
    replyTextarea.rows = 2;
    autoGrow(replyTextarea);
    replyRow.appendChild(replyTextarea);

    var btnRow = document.createElement('div');
    btnRow.className = 'scholia-overlay-reply-buttons';

    var replyBtn = document.createElement('button');
    replyBtn.className = 'scholia-btn-primary';
    replyBtn.textContent = 'Reply';
    replyBtn.addEventListener('click', function () {
      var text = replyTextarea.value.trim();
      if (!text) return;
      wsSend({ type: 'reply', annotation_id: ann.id, body: text, creator: creatorName });
      replyTextarea.value = '';
    });
    btnRow.appendChild(replyBtn);

    // Preview button (uses Pandoc when P is active)
    var previewDiv = null;
    var previewBtn = document.createElement('button');
    previewBtn.className = 'scholia-btn-ghost';
    previewBtn.textContent = 'Preview';
    previewBtn.addEventListener('click', function () {
      if (previewDiv) {
        // Hide preview, show textarea
        previewDiv.remove();
        previewDiv = null;
        replyTextarea.style.display = '';
        previewBtn.textContent = 'Preview';
      } else {
        // Show preview, hide textarea
        previewDiv = document.createElement('div');
        previewDiv.className = 'scholia-message-body scholia-preview-body';
        previewDiv.innerHTML = renderCommentBody(replyTextarea.value);
        replyTextarea.style.display = 'none';
        replyRow.insertBefore(previewDiv, btnRow);
        previewBtn.textContent = 'Edit';
        // If Pandoc active, upgrade preview via server
        if (overlayPandocActive) {
          var raw = replyTextarea.value;
          if (pandocCache.has(raw)) {
            previewDiv.innerHTML = pandocCache.get(raw);
            postProcessPandocHtml(previewDiv);
          } else {
            var reqId = 'pandoc-' + Date.now() + '-' + Math.random().toString(36).slice(2, 6);
            pandocCallbacks.set(reqId, function (html) {
              pandocCache.set(raw, html);
              if (previewDiv) {
                previewDiv.innerHTML = html;
                postProcessPandocHtml(previewDiv);
              }
            });
            wsSend({ type: 'render_markdown', text: raw, request_id: reqId });
          }
        }
      }
    });
    btnRow.appendChild(previewBtn);

    var status = ann['scholia:status'] || 'open';
    if (status === 'open') {
      var resolveBtn = document.createElement('button');
      resolveBtn.className = 'scholia-btn-ghost';
      resolveBtn.textContent = 'Resolve';
      resolveBtn.addEventListener('click', function () {
        wsSend({ type: 'resolve', annotation_id: ann.id });
        wsSend({ type: 'mark_read', annotation_id: ann.id });
        state[ann.id] = { lastReadAt: new Date().toISOString() };
      });
      btnRow.appendChild(resolveBtn);
    } else {
      var unresolveBtn = document.createElement('button');
      unresolveBtn.className = 'scholia-btn-ghost';
      unresolveBtn.textContent = 'Unresolve';
      unresolveBtn.addEventListener('click', function () {
        wsSend({ type: 'unresolve', annotation_id: ann.id });
      });
      btnRow.appendChild(unresolveBtn);
    }

    replyRow.appendChild(btnRow);
    panel.appendChild(replyRow);

    backdrop.appendChild(panel);
    document.body.appendChild(backdrop);
    activeOverlay = { backdrop: backdrop, annotationId: ann.id };

    // Escape to close
    document.addEventListener('keydown', overlayEscHandler);

    // Scroll thread to bottom
    threadBody.scrollTop = threadBody.scrollHeight;

    // Auto-render all messages via Pandoc (on by default)
    for (var pi = 0; pi < overlayBodies.length; pi++) {
      (function (bEl) {
        var raw = bEl.dataset.raw;
        if (pandocCache.has(raw)) {
          bEl.innerHTML = pandocCache.get(raw);
          postProcessPandocHtml(bEl);
        } else {
          var reqId = 'pandoc-' + Date.now() + '-' + Math.random().toString(36).slice(2, 6);
          pandocCallbacks.set(reqId, function (html) {
            pandocCache.set(raw, html);
            if (overlayPandocActive && !bEl.classList.contains('scholia-raw-view')) {
              bEl.innerHTML = html;
              postProcessPandocHtml(bEl);
            }
          });
          wsSend({ type: 'render_markdown', text: raw, request_id: reqId });
        }
      })(overlayBodies[pi]);
    }
  }

  function closeOverlay() {
    if (!activeOverlay) return;
    activeOverlay.backdrop.remove();
    activeOverlay = null;
    document.removeEventListener('keydown', overlayEscHandler);
  }

  function overlayEscHandler(e) {
    if (e.key === 'Escape') closeOverlay();
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

      if (!showResolved && status === 'resolved') continue;
      if (!showRead && !isUnread(ann)) continue;

      var selector = ann.target && ann.target.selector;
      var srcSel = ann.target && ann.target['scholia:sourceSelector'];
      var via = ann['scholia:via'];

      if ((!selector || !selector.exact) && (!srcSel || !srcSel.exact)) {
        orphanIds.add(ann.id);
        continue;
      }

      // CLI annotations: source selector is authoritative (browser selector is approximate)
      // Browser annotations: browser selector is authoritative (source selector is fallback)
      var range = null;
      if (via === 'cli') {
        if (srcSel && srcSel.exact) range = TextQuoteAnchor.toRangeRecoverable(docEl, srcSel);
        if (!range && selector && selector.exact) range = TextQuoteAnchor.toRange(docEl, selector);
      } else {
        if (selector && selector.exact) range = TextQuoteAnchor.toRange(docEl, selector);
        if (!range && srcSel && srcSel.exact) range = TextQuoteAnchor.toRangeRecoverable(docEl, srcSel);
      }

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
          var iconTip = document.createElement('div');
          iconTip.className = 'scholia-orphan-tooltip';
          iconTip.textContent = 'Anchor text not found. Click to re-anchor.';
          icon.appendChild(iconTip);
          icon.addEventListener('click', (function (theId) {
            return function (e) {
              e.stopPropagation();
              startReanchor(theId);
            };
          })(id));
          // Insert before anchor text span
          var anchorSpan = headerEl.querySelector('.scholia-anchor-text');
          if (anchorSpan) {
            headerEl.insertBefore(icon, anchorSpan);
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

    // Reserve space for new-comment form
    var newCommentEl = document.getElementById('scholia-new-comment');
    var minY = parseFloat(getComputedStyle(sidebarEl).paddingTop) || 0;
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

      if (entry.card !== reanchorCard) {
        entry.card.style.top = top + 'px';
      }
      currentY = top + (shouldExpand ? entry.expandedH : entry.collapsedH) + 4;
    }

    // Remove stale divider + label if no orphans this render
    var staleDivider = sidebarEl.querySelector('.scholia-orphan-divider');
    var staleLabel = sidebarEl.querySelector('.scholia-orphan-label');
    if (orphans.length === 0) {
      if (staleDivider) staleDivider.remove();
      if (staleLabel) staleLabel.remove();
    }

    // Orphan section: divider (only if there are positioned cards above) + label + cards
    if (orphans.length > 0) {
      // Divider only makes sense when there are positioned cards to separate from
      if (positioned.length > 0) {
        currentY += 16;
        var divider = sidebarEl.querySelector('.scholia-orphan-divider');
        if (!divider) {
          divider = document.createElement('div');
          divider.className = 'scholia-orphan-divider';
          sidebarEl.appendChild(divider);
        }
        divider.style.position = 'absolute';
        divider.style.left = '0.75rem';
        divider.style.right = '0.75rem';
        divider.style.top = currentY + 'px';
        currentY += divider.offsetHeight + 8;
      } else {
        if (staleDivider) staleDivider.remove();
      }

      // Label always shown when there are orphans
      var label = sidebarEl.querySelector('.scholia-orphan-label');
      if (!label) {
        label = document.createElement('div');
        label.className = 'scholia-orphan-label';
        var labelText = document.createElement('span');
        labelText.textContent = 'Orphaned threads';
        var helpIcon = document.createElement('span');
        helpIcon.className = 'scholia-orphan-label-help';
        helpIcon.textContent = '?';
        var tooltip = document.createElement('div');
        tooltip.className = 'scholia-orphan-tooltip';
        tooltip.textContent = 'The text to which these "orphaned" threads are anchored can no longer be found in the document. This happens when the anchored passage is edited or deleted. The comments are preserved here so you don\'t lose them.';
        label.appendChild(labelText);
        label.appendChild(helpIcon);
        label.appendChild(tooltip);
        sidebarEl.appendChild(label);
      }
      label.style.position = 'absolute';
      label.style.left = '0.75rem';
      label.style.top = currentY + 'px';
      currentY += label.offsetHeight + 8;
    }
    for (var o = 0; o < orphans.length; o++) {
      // Skip card being re-anchored — it controls its own position
      if (orphans[o] === reanchorCard) continue;
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

  // ── Compact mode: click highlight → open overlay ───
  docEl.addEventListener('click', function (e) {
    if (!compactMode) return;
    var mark = e.target.closest && e.target.closest('.scholia-highlight');
    if (!mark) return;
    var annId = mark.dataset.annotationId;
    for (var i = 0; i < comments.length; i++) {
      if (comments[i].id === annId) {
        openOverlay(comments[i]);
        return;
      }
    }
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
    if (readonlyMode) return;
    if (sidebarHidden && !compactMode) return;
    if (reanchorAnnotationId) return;  // re-anchor mode handles selection
    var sel = window.getSelection();
    if (!sel || sel.isCollapsed || !sel.rangeCount) return;

    var range = sel.getRangeAt(0);
    if (!docEl.contains(range.commonAncestorContainer)) return;

    // Ignore if inside the comment form
    if (pendingForm && pendingForm.contains(range.commonAncestorContainer)) return;

    // Snap selection to math expression boundaries
    var snapped = TextQuoteAnchor.snapToMathBoundaries(range);

    var selector = TextQuoteAnchor.fromRange(docEl, snapped);
    if (!selector.exact.trim()) return;

    // Build source-space selector for CLI resolution
    var sourceSelector = TextQuoteAnchor.fromRangeRecoverable(docEl, snapped);
    selector._source = sourceSelector;

    // Update visual selection to reflect snapped boundaries
    sel.removeAllRanges();
    sel.addRange(snapped);

    if (compactMode) {
      showCompactCommentForm(selector);
      return;
    }

    // Position: at selection top, or viewport top if selection starts off-screen
    var rangeRect = snapped.getBoundingClientRect();
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
    var displayExact = (selector._source && selector._source.exact) || selector.exact;
    var excerpt = displayExact.slice(0, 80);
    anchorDiv.textContent = '\u201c' + excerpt + (displayExact.length > 80 ? '\u2026' : '') + '\u201d';
    form.appendChild(anchorDiv);

    var textarea = document.createElement('textarea');
    textarea.name = 'new-comment';
    textarea.placeholder = 'Add a comment\u2026';
    textarea.rows = 3;
    autoGrow(textarea);
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
        var payload = {
          type: 'new_comment',
          exact: pendingSelector.exact,
          prefix: pendingSelector.prefix,
          suffix: pendingSelector.suffix,
          body: text
        };
        if (pendingSelector._source) {
          payload.source_exact = pendingSelector._source.exact;
          payload.source_prefix = pendingSelector._source.prefix;
          payload.source_suffix = pendingSelector._source.suffix;
        }
        wsSend(payload);
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

    var newCommentPreviewDiv = null;
    var newCommentPreviewBtn = document.createElement('button');
    newCommentPreviewBtn.className = 'scholia-btn scholia-btn-ghost';
    newCommentPreviewBtn.textContent = 'Preview';
    newCommentPreviewBtn.addEventListener('click', function (e) {
      e.stopPropagation();
      if (newCommentPreviewDiv) {
        newCommentPreviewDiv.remove();
        newCommentPreviewDiv = null;
        textarea.style.display = '';
        newCommentPreviewBtn.textContent = 'Preview';
      } else {
        newCommentPreviewDiv = document.createElement('div');
        newCommentPreviewDiv.className = 'scholia-message-body scholia-preview-body';
        newCommentPreviewDiv.innerHTML = renderCommentBody(textarea.value);
        textarea.style.display = 'none';
        // Insert before the actions row
        form.insertBefore(newCommentPreviewDiv, actions);
        newCommentPreviewBtn.textContent = 'Edit';
      }
    });
    actions.appendChild(newCommentPreviewBtn);

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
    if (pendingForm && !pendingForm.contains(e.target)) {
      dismissCommentPrompt();
    }
    if (compactForm && !compactForm.contains(e.target)) {
      dismissCompactComment();
    }
  });

  // Forward keyboard to textarea when prompt is visible but not focused
  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape' && compactForm) {
      dismissCompactComment();
      return;
    }
    if (sidebarHidden || !pendingForm) return;
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

  // ── Compact mode: bottom-sheet new comment form ────

  var compactForm = null;
  var compactSelector = null;

  function showCompactCommentForm(selector) {
    dismissCompactComment();
    compactSelector = selector;

    // Highlight the selected text
    var r = TextQuoteAnchor.toRange(docEl, selector);
    if (r) {
      window.getSelection().removeAllRanges();
      var marks = wrapRange(r, '__pending__');
      highlights.set('__pending__', marks);
    }

    var form = document.createElement('div');
    form.className = 'scholia-compact-comment';

    var anchorDiv = document.createElement('div');
    anchorDiv.className = 'scholia-new-comment-anchor';
    var displayExact = (selector._source && selector._source.exact) || selector.exact;
    var excerpt = displayExact.slice(0, 80);
    anchorDiv.textContent = '\u201c' + excerpt + (displayExact.length > 80 ? '\u2026' : '') + '\u201d';
    form.appendChild(anchorDiv);

    var textarea = document.createElement('textarea');
    textarea.name = 'compact-new-comment';
    textarea.placeholder = 'Add a comment\u2026';
    textarea.rows = 2;
    autoGrow(textarea);
    form.appendChild(textarea);

    var actions = document.createElement('div');
    actions.className = 'scholia-new-comment-actions';

    var cancelBtn = document.createElement('button');
    cancelBtn.className = 'scholia-btn scholia-btn-cancel';
    cancelBtn.textContent = 'Cancel';
    cancelBtn.addEventListener('click', function (e) {
      e.stopPropagation();
      dismissCompactComment();
    });
    actions.appendChild(cancelBtn);

    var submitBtn = document.createElement('button');
    submitBtn.className = 'scholia-btn scholia-btn-submit';
    submitBtn.textContent = 'Comment';
    submitBtn.addEventListener('click', function (e) {
      e.stopPropagation();
      var text = textarea.value.trim();
      if (!text) return;
      var compactPayload = {
        type: 'new_comment',
        exact: compactSelector.exact,
        prefix: compactSelector.prefix,
        suffix: compactSelector.suffix,
        body: text
      };
      if (compactSelector._source) {
        compactPayload.source_exact = compactSelector._source.exact;
        compactPayload.source_prefix = compactSelector._source.prefix;
        compactPayload.source_suffix = compactSelector._source.suffix;
      }
      wsSend(compactPayload);
      dismissCompactComment();
    });
    actions.appendChild(submitBtn);

    var compactPreviewDiv = null;
    var previewBtn = document.createElement('button');
    previewBtn.className = 'scholia-btn scholia-btn-ghost';
    previewBtn.textContent = 'Preview';
    previewBtn.addEventListener('click', function (e) {
      e.stopPropagation();
      if (compactPreviewDiv) {
        compactPreviewDiv.remove();
        compactPreviewDiv = null;
        textarea.style.display = '';
        previewBtn.textContent = 'Preview';
      } else {
        compactPreviewDiv = document.createElement('div');
        compactPreviewDiv.className = 'scholia-message-body scholia-preview-body';
        compactPreviewDiv.innerHTML = renderCommentBody(textarea.value);
        textarea.style.display = 'none';
        form.insertBefore(compactPreviewDiv, actions);
        previewBtn.textContent = 'Edit';
      }
    });
    actions.appendChild(previewBtn);

    form.appendChild(actions);
    document.body.appendChild(form);
    compactForm = form;
    textarea.focus();
  }

  function dismissCompactComment() {
    if (compactForm) {
      compactForm.remove();
      compactForm = null;
    }
    compactSelector = null;
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

  // ── Re-anchor orphaned threads ─────────────────────
  // Click orphan ? icon → inline prompt on card → select text → auto-accepts

  var reanchorAnnotationId = null;
  var reanchorPrompt = null;
  var reanchorCard = null;
  var reanchorOriginalTop = null;

  function reanchorCenterY() {
    var sidebarRect = sidebarEl.getBoundingClientRect();
    var cardH = reanchorCard ? reanchorCard.offsetHeight : 0;
    // Center of visible viewport, converted to sidebar-relative coords
    var viewportCenterY = window.innerHeight / 2;
    return viewportCenterY - sidebarRect.top - (cardH / 2);
  }

  function startReanchor(annotationId) {
    cancelReanchor();
    dismissCommentPrompt();
    reanchorAnnotationId = annotationId;

    // Find the card and add inline prompt
    var card = sidebarEl.querySelector('[data-annotation-id="' + annotationId + '"]');
    if (!card) return;
    reanchorCard = card;
    reanchorOriginalTop = parseFloat(card.style.top) || 0;

    reanchorPrompt = document.createElement('div');
    reanchorPrompt.className = 'scholia-reanchor-prompt';
    reanchorPrompt.innerHTML = 'Select text in the document to re-anchor\u2026 '
      + '<button class="scholia-btn scholia-btn-cancel">Cancel</button>';
    reanchorPrompt.querySelector('button').addEventListener('click', function (e) {
      e.stopPropagation();
      cancelReanchor();
    });
    card.appendChild(reanchorPrompt);
    card.classList.add('scholia-reanchoring');

    // Dim the rest of the sidebar (fade in)
    var dim = document.createElement('div');
    dim.className = 'scholia-reanchor-dim';
    sidebarEl.appendChild(dim);
    // Force layout before adding class so transition fires
    dim.offsetHeight;
    dim.classList.add('active');

    // Animate card to vertical center
    card.style.transition = 'top 0.35s ease';
    card.style.top = reanchorCenterY() + 'px';
  }

  function cancelReanchor() {
    if (!reanchorCard) { reanchorAnnotationId = null; return; }
    var card = reanchorCard;

    // Fade out dim
    var dim = sidebarEl.querySelector('.scholia-reanchor-dim');
    if (dim) dim.classList.remove('active');

    // Animate back to original position
    card.style.transition = 'top 0.35s ease';
    card.style.top = reanchorOriginalTop + 'px';

    // Clean up after animation
    setTimeout(function () {
      card.style.transition = '';
      card.classList.remove('scholia-reanchoring');
      if (reanchorPrompt) { reanchorPrompt.remove(); reanchorPrompt = null; }
      if (dim) dim.remove();
      reanchorCard = null;
      reanchorOriginalTop = null;
      reanchorAnnotationId = null;
      positionCards();
    }, 350);
  }

  // Keep card centered while scrolling in reanchor mode
  window.addEventListener('scroll', function () {
    if (!reanchorCard) return;
    reanchorCard.style.transition = 'none';
    reanchorCard.style.top = reanchorCenterY() + 'px';
  });

  // Intercept text selection during re-anchor mode — auto-accept
  docEl.addEventListener('mouseup', function () {
    if (!reanchorAnnotationId || !reanchorCard) return;
    var sel = window.getSelection();
    if (!sel || sel.isCollapsed || !sel.rangeCount) return;

    var range = sel.getRangeAt(0);
    if (!docEl.contains(range.commonAncestorContainer)) return;

    // Snap selection to math expression boundaries
    var snapped = TextQuoteAnchor.snapToMathBoundaries(range);

    var selector = TextQuoteAnchor.fromRange(docEl, snapped);
    if (!selector.exact.trim()) return;

    // Build source-space selector for CLI resolution
    var sourceSelector = TextQuoteAnchor.fromRangeRecoverable(docEl, snapped);

    var annId = reanchorAnnotationId;
    var card = reanchorCard;

    // Send reanchor
    var reanchorPayload = {
      type: 'reanchor',
      annotation_id: annId,
      exact: selector.exact,
      prefix: selector.prefix,
      suffix: selector.suffix,
      source_exact: sourceSelector.exact,
      source_prefix: sourceSelector.prefix,
      source_suffix: sourceSelector.suffix,
    };
    wsSend(reanchorPayload);
    window.getSelection().removeAllRanges();

    // Clean up prompt, fade out dim
    if (reanchorPrompt) { reanchorPrompt.remove(); reanchorPrompt = null; }
    var dim = sidebarEl.querySelector('.scholia-reanchor-dim');
    if (dim) dim.classList.remove('active');

    // Animate card toward where the new anchor is in the document
    var marks = TextQuoteAnchor.toRange(docEl, selector);
    if (marks) {
      var sidebarTop = sidebarEl.getBoundingClientRect().top;
      var targetY = marks.getBoundingClientRect().top - sidebarTop + sidebarEl.scrollTop;
      card.style.transition = 'top 0.35s ease';
      card.style.top = targetY + 'px';
    }

    setTimeout(function () {
      card.style.transition = '';
      card.classList.remove('scholia-reanchoring');
      if (dim) dim.remove();
      reanchorCard = null;
      reanchorOriginalTop = null;
      reanchorAnnotationId = null;
    }, 350);
  }, true);  // capture phase so it runs before the new-comment handler

  // Escape cancels re-anchor mode
  document.addEventListener('keydown', function (e) {
    if (reanchorAnnotationId && e.key === 'Escape') {
      cancelReanchor();
      window.getSelection().removeAllRanges();
    }
  });

  // ── Citation hover tooltips ─────────────────────────

  var citationTooltip = null;
  var citationHideTimer = null;

  function setupCitationTooltips() {
    setupCitationTooltipsIn(docEl);
  }

  function setupCitationTooltipsIn(container) {
    // Pandoc with link-citations creates <a href="#ref-KEY"> inside <span class="citation">
    var links = container.querySelectorAll('a[href^="#ref-"]');
    for (var i = 0; i < links.length; i++) {
      links[i].addEventListener('mouseenter', showCitationTooltip);
      links[i].addEventListener('mouseleave', scheduleCitationHide);
      // Prevent clicking the citation from jumping to the bibliography
      links[i].addEventListener('click', function (e) {
        if (citationTooltip) e.preventDefault();
      });
    }
  }

  function showCitationTooltip(e) {
    var link = e.target.closest('a[href^="#ref-"]');
    if (!link) return;
    var refId = link.getAttribute('href').slice(1); // strip #
    // Look in the closest message body first (for comment citations), fall back to document
    var messageBody = link.closest('.scholia-message-body');
    var refEl = messageBody ? messageBody.querySelector('#' + CSS.escape(refId)) : null;
    if (!refEl) refEl = document.getElementById(refId);
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
    if (sidebarHidden) {
      aboveIndicator.style.display = 'none';
      belowIndicator.style.display = 'none';
      return;
    }
    var cards = sidebarEl.querySelectorAll('.scholia-card');
    var viewH = window.innerHeight;
    var toolbarH = toolbarEl.offsetHeight || 0;
    var above = 0, aboveOrph = 0, below = 0, belowOrph = 0;

    for (var i = 0; i < cards.length; i++) {
      var r = cards[i].getBoundingClientRect();
      var isOrph = cards[i].classList.contains('scholia-orphan');
      if (r.bottom < toolbarH) { above++; if (isOrph) aboveOrph++; }
      else if (r.top > viewH) { below++; if (isOrph) belowOrph++; }
    }

    // Align indicators with sidebar
    var sr = sidebarEl.getBoundingClientRect();
    aboveIndicator.style.top = toolbarH + 'px';
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

  // ── Sidebar resize handle ──────────────────────────

  var SIDEBAR_MIN = 200;
  var SIDEBAR_MAX = 600;
  var SIDEBAR_COLLAPSE = 80;  // drag past this to hide

  resizeHandle.addEventListener('mousedown', function (e) {
    e.preventDefault();
    resizeHandle.classList.add('dragging');
    containerEl.style.transition = 'none';

    function onMove(e) {
      var newWidth = window.innerWidth - e.clientX;
      if (newWidth < SIDEBAR_COLLAPSE) {
        // Collapse: hide sidebar
        if (!sidebarHidden) {
          sidebarHidden = true;
          containerEl.classList.add('scholia-sidebar-hidden');
          clearAllHighlights();
          dismissCommentPrompt();
          renderToolbar();
        }
        return;
      }
      // Uncollapse if was hidden
      if (sidebarHidden) {
        sidebarHidden = false;
        containerEl.classList.remove('scholia-sidebar-hidden');
        renderToolbar();
        scheduleRender();
      }
      var clamped = Math.max(SIDEBAR_MIN, Math.min(SIDEBAR_MAX, newWidth));
      containerEl.style.setProperty('--sidebar-width', clamped + 'px');
      positionCards();
    }

    function onUp() {
      resizeHandle.classList.remove('dragging');
      containerEl.style.transition = '';
      document.removeEventListener('mousemove', onMove);
      document.removeEventListener('mouseup', onUp);
    }

    document.addEventListener('mousemove', onMove);
    document.addEventListener('mouseup', onUp);
  });

  // ── Init ───────────────────────────────────────────

  // Set initial sidenotes CSS state
  if (!sidenotesEnabled) docEl.classList.add('scholia-no-sidenotes');

  // Apply persisted preferences
  if (darkMode) document.body.classList.add('scholia-dark');
  if (fontMode !== 'default') document.body.classList.add('scholia-font-' + fontMode);
  if (uiZoom !== 100) applyZoom();

  // Track system theme changes for 'system' mode
  window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', function (e) {
    if (themeMode !== 'system') return;
    darkMode = e.matches;
    document.body.classList.toggle('scholia-dark', darkMode);
    renderToolbar();
  });

  renderToolbar();
  connectWS();
  initMarkdownIt();
  if (!md) {
    window.addEventListener('load', function () {
      initMarkdownIt();
      rerenderCommentBodies();
    });
  }
  renderSidebar();

  // KaTeX and mermaid are loaded with defer, so wait for window load
  window.addEventListener('load', function () {
    if (window.mermaid) window.mermaid.initialize({ startOnLoad: false });
    buildToc();
    rerenderMath();
    renderMermaid();
    rerenderCommentBodies();
    decorateCodeBlocks();
    setupCitationTooltips();
    reanchorAll();
    positionCards();
  });

  // Reposition cards on resize (layout may change)
  window.addEventListener('resize', positionCards);

  // ── Compact mode: viewport too narrow for sidebar ──
  var COMPACT_ENTER = 754;
  var COMPACT_LEAVE = 800;

  function checkCompact() {
    var vw = window.innerWidth;
    if (!compactMode && vw < COMPACT_ENTER) {
      compactMode = true;
      containerEl.classList.add('scholia-compact');
      dismissCommentPrompt();
      if (!sidebarHidden) { reanchorAll(); }
      renderToolbar();
    } else if (compactMode && vw > COMPACT_LEAVE) {
      compactMode = false;
      containerEl.classList.remove('scholia-compact');
      dismissCompactComment();
      if (!sidebarHidden) {
        scheduleRender();
      }
      renderToolbar();
    }
  }

  window.addEventListener('resize', checkCompact);
  checkCompact();

  // Responsive sidenotes: toggle based on doc pane width, not viewport.
  // Hysteresis prevents oscillation at the boundary — content width changes
  // when the class toggles (60% → 100%), so we use separate thresholds.
  var NARROW_ENTER = 750;
  var NARROW_LEAVE = 820;
  var resizeObs = new ResizeObserver(function (entries) {
    var width = entries[0].contentRect.width;
    var isNarrow = docEl.classList.contains('scholia-narrow-doc');
    if (!isNarrow && width < NARROW_ENTER) {
      docEl.classList.add('scholia-narrow-doc');
    } else if (isNarrow && width > NARROW_LEAVE) {
      docEl.classList.remove('scholia-narrow-doc');
    }
  });
  resizeObs.observe(docEl);

})();

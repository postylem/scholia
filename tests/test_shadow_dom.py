from pathlib import Path

ROOT = Path(__file__).parent.parent


def _load_template():
    return (ROOT / "scholia" / "template.html").read_text()


def _load_js():
    return (ROOT / "scholia" / "static" / "scholia.js").read_text()


def _load_css():
    return (ROOT / "scholia" / "static" / "scholia.css").read_text()


# ── Template structure ──


def test_template_has_scholia_sidebar_element():
    t = _load_template()
    assert "<scholia-sidebar>" in t
    assert "</scholia-sidebar>" in t


def test_template_has_no_old_container():
    """Old grid container removed; shadow DOM creates these now."""
    t = _load_template()
    assert 'id="scholia-container"' not in t
    assert 'id="scholia-toolbar"' not in t
    assert 'id="scholia-sidebar"' not in t
    assert 'id="scholia-resize-handle"' not in t


def test_template_has_highlight_styles_inline():
    t = _load_template()
    assert "mark.scholia-highlight" in t


def test_template_has_quarto_placeholders():
    t = _load_template()
    assert "{{QUARTO_HEAD}}" in t
    assert "{{IS_QUARTO}}" in t


def test_template_has_content_css_placeholder():
    """Pandoc template includes scholia.css for content styling."""
    t = _load_template()
    assert "{{CONTENT_CSS}}" in t


# ── JS shadow DOM ──


def test_js_attaches_shadow():
    js = _load_js()
    assert "attachShadow" in js


def test_js_loads_css_in_shadow():
    js = _load_js()
    assert "/static/scholia.css" in js


def test_js_creates_shadow_elements():
    js = _load_js()
    assert "'scholia-toolbar'" in js
    assert "'scholia-sidebar'" in js
    assert "'scholia-resize-handle'" in js


def test_js_injects_body_grid_layout():
    js = _load_js()
    assert "grid-template-columns" in js
    assert "document.head.appendChild" in js


def test_js_no_containerEl():
    """containerEl was replaced with document.body references."""
    js = _load_js()
    assert "containerEl" not in js


def test_js_uses_composed_path():
    """Shadow DOM event handling uses composedPath."""
    js = _load_js()
    assert "composedPath" in js


def test_js_quarto_flag():
    js = _load_js()
    assert "__SCHOLIA_IS_QUARTO__" in js
    assert "scholia-quarto" in js


# ── CSS shadow compatibility ──


def test_css_has_host_selector():
    css = _load_css()
    assert ":host" in css


def test_css_no_id_selectors_for_shadow_elements():
    """Shadow-internal elements use class selectors, not IDs."""
    css = _load_css()
    assert "#scholia-toolbar" not in css
    assert "#scholia-sidebar" not in css
    assert "#scholia-resize-handle" not in css
    assert "#scholia-container" not in css


def test_css_has_grid_participation():
    css = _load_css()
    assert "grid-column: 1 / -1" in css  # toolbar spans full width
    assert "grid-row: 1" in css  # toolbar in first row


def test_css_no_highlight_styles():
    """Highlight styles moved to template inline <style>."""
    css = _load_css()
    assert "mark.scholia-highlight" not in css


def test_css_dark_mode_uses_host():
    """Dark mode for shadow elements uses :host(.scholia-dark)."""
    css = _load_css()
    assert ":host(.scholia-dark)" in css


# ── Server template filling ──


def test_inject_scholia_into_quarto():
    from scholia.server import _inject_scholia_into_quarto

    quarto_html = (
        "<!DOCTYPE html><html><head><title>Test</title></head>"
        '<body class="fullcontent"><main class="content">Hello</main></body></html>'
    )
    page = _inject_scholia_into_quarto(quarto_html, Path("/tmp/test.qmd"))
    assert "<scholia-sidebar>" in page
    assert "scholia.js" in page
    assert 'id="scholia-doc"' in page
    assert "__SCHOLIA_IS_QUARTO__ = true" in page
    assert 'class="fullcontent"' in page  # body classes preserved
    assert 'class="content"' in page  # main classes preserved
    assert "mark.scholia-highlight" in page  # highlight CSS injected


def test_fill_template_non_quarto():
    from scholia.server import _fill_template

    t = _load_template()
    page = _fill_template(
        t,
        title="Test",
        html="<p>Hello</p>",
        doc_path=Path("/tmp/test.md"),
    )
    assert "__SCHOLIA_IS_QUARTO__ = false" in page


def test_is_quarto():
    from scholia.server import _is_quarto

    assert _is_quarto(Path("test.qmd"))
    assert _is_quarto(Path("test.rmd"))
    assert _is_quarto(Path("test.Qmd"))
    assert not _is_quarto(Path("test.md"))
    assert not _is_quarto(Path("test.html"))

from ntf_insight.app.fonts import _find_family
from ntf_insight.app.styles import stylesheet_for


def test_font_match_prefers_exact_corporate_family() -> None:
    available = ["Arial", "Corporate S Pro", "Corporate A Pro"]

    assert _find_family(available, ("Corporate S Pro", "Corporate S")) == "Corporate S Pro"
    assert _find_family(available, ("Corporate A Pro", "Corporate A")) == "Corporate A Pro"


def test_stylesheet_uses_resolved_body_and_heading_fonts() -> None:
    style = stylesheet_for(
        "light",
        body_font="Corporate S Pro",
        heading_font="Corporate A Pro",
    )

    assert 'font-family: "Corporate S Pro"' in style
    assert 'font-family: "Corporate A Pro"' in style


def test_resolve_fonts_uses_safe_fallback_if_qt_reports_no_fonts(monkeypatch) -> None:
    """Auf GitHub-Windows-Runnern meldet Qt-Offscreen oft keine Schriftarten."""
    import ntf_insight.app.fonts as fonts

    monkeypatch.delenv("NTF_INSIGHT_FONT_DIR", raising=False)
    monkeypatch.delenv("NTF_INSIGHT_BODY_FONT_FAMILY", raising=False)
    monkeypatch.delenv("NTF_INSIGHT_HEADING_FONT_FAMILY", raising=False)

    class EmptyFontDatabase:
        @staticmethod
        def families():
            return []

    monkeypatch.setattr(fonts, "QFontDatabase", EmptyFontDatabase)
    resolved = fonts.resolve_fonts()

    assert resolved.body_family == "Segoe UI"
    assert resolved.heading_family == "Segoe UI"
    assert resolved.corporate_body is False
    assert resolved.corporate_heading is False
    assert resolved.loaded_font_files == ()

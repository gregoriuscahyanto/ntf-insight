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

from ntf_insight.app.styles import stylesheet_for


def test_light_theme_explicitly_uses_dark_text_on_light_surfaces() -> None:
    style = stylesheet_for("light")

    assert "color: #111827" in style
    assert "background-color: #ffffff" in style
    assert "selection-color: #111827" in style


def test_dark_theme_explicitly_uses_light_text_on_dark_surfaces() -> None:
    style = stylesheet_for("dark")

    assert "color: #f9fafb" in style
    assert "background-color: #111827" in style
    assert "selection-color: #ffffff" in style

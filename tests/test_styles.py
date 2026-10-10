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


def test_single_primary_cluster_action_uses_graphite_with_readable_contrast() -> None:
    for theme in ("light", "dark"):
        style = stylesheet_for(theme)
        assert "QPushButton#ClusterStartButton {" in style
        assert "background-color: #252a2e;" in style
        assert "color: #ffffff;" in style
        assert "QPushButton#ClusterStartButton:hover {" in style
        assert "QPushButton#ClusterStartButton:disabled {" in style

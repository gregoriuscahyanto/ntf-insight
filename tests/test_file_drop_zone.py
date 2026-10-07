import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QMimeData, QUrl

from ntf_insight.app.widgets.file_drop_zone import FileDropZone


def test_drop_zone_extracts_only_local_files(tmp_path) -> None:
    source = tmp_path / "short-test.xml"
    source.write_text("synthetic", encoding="utf-8")
    folder = tmp_path / "folder"
    folder.mkdir()

    mime = QMimeData()
    mime.setUrls(
        [
            QUrl.fromLocalFile(str(source)),
            QUrl.fromLocalFile(str(folder)),
            QUrl("https://example.com/not-local"),
        ]
    )

    assert FileDropZone.local_files(mime) == [source]

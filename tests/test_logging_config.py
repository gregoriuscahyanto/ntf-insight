import logging

from ntf_insight.app.logging_config import configure_logging


def test_logging_configuration_creates_local_log_file(tmp_path) -> None:
    log_path = configure_logging(tmp_path)
    logging.getLogger("ntf_insight.test").info("synthetic log message")

    assert log_path.exists()

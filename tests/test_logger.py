import logging

from scripts.logger import get_component_logger, get_logger_name, setup_logger


def test_setup_logger_uses_configured_logger_name(base_config, tmp_path):
    base_config.logging["name"] = "briefitalia"
    base_config.logging["file"] = str(tmp_path / "app.log")

    logger = setup_logger(base_config, "test-run")

    try:
        assert logger.name == "briefitalia"
        assert logger.handlers
    finally:
        logger.handlers.clear()


def test_get_component_logger_uses_configured_base_name(base_config):
    base_config.logging["name"] = "briefitalia"

    logger = get_component_logger("post-audio", base_config)

    assert logger.name == "briefitalia.post-audio"


def test_get_logger_name_defaults_to_briefberlin():
    assert get_logger_name(component="worker") == "briefberlin.worker"


def test_setup_logger_supports_dict_config(tmp_path):
    logger = setup_logger(
        {
            "logging": {
                "name": "briefitalia",
                "level": "INFO",
                "format": "json",
                "file": str(tmp_path / "app.log"),
            }
        },
        "test-run",
    )

    try:
        assert logger is logging.getLogger("briefitalia")
    finally:
        logger.handlers.clear()

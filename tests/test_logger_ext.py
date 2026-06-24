import json
import logging

from src.monitoring.logging.logger import setup_json_logger


def test_json_formatter():
    logger = setup_json_logger("test_logger")
    # capture output
    import io

    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    from src.monitoring.logging.logger import JsonFormatter

    handler.setFormatter(JsonFormatter())
    logger.addHandler(handler)
    logger.propagate = False

    logger.info("Teste", extra={"user": "admin"})

    output = stream.getvalue()
    data = json.loads(output)

    assert data["message"] == "Teste"
    assert data["level"] == "INFO"
    assert data["logger"] == "test_logger"
    assert data["user"] == "admin"


def test_json_formatter_exception():
    logger = setup_json_logger("test_logger2")
    import io

    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    from src.monitoring.logging.logger import JsonFormatter

    handler.setFormatter(JsonFormatter())
    logger.addHandler(handler)
    logger.propagate = False

    try:
        1 / 0
    except ZeroDivisionError:
        logger.exception("Erro")

    output = stream.getvalue()
    data = json.loads(output)

    assert "ZeroDivisionError" in data["exc_info"]

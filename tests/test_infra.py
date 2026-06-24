import json
import logging

from src.monitoring.logging.logger import JsonFormatter
from src.monitoring.metrics.metrics import MetricsRegistry


def test_metrics_singleton():
    m1 = MetricsRegistry()
    m2 = MetricsRegistry()
    assert m1 is m2


def test_metrics_counters():
    metrics = MetricsRegistry()
    metrics.reset()
    metrics.inc("cache_hits")
    metrics.add("bytes_downloaded", 1024)

    stats = metrics.get_stats()
    assert stats["cache_hits"] == 1
    assert stats["bytes_downloaded"] == 1024


def test_json_logger(capsys):
    logger = logging.getLogger("test_json")
    logger.setLevel(logging.INFO)

    # We need a handler that writes to a buffer or stdout
    import sys

    handler = logging.StreamHandler(sys.stdout)
    formatter = JsonFormatter()
    handler.setFormatter(formatter)
    logger.addHandler(handler)

    logger.info(
        "Test event", extra={"event": "chunk_download", "chunk": 0, "file": "doc.pdf"}
    )

    captured = capsys.readouterr()
    log_output = captured.out.strip()

    data = json.loads(log_output)
    assert data["event"] == "chunk_download"
    assert data["chunk"] == 0
    assert data["file"] == "doc.pdf"
    assert data["message"] == "Test event"
    assert data["level"] == "INFO"

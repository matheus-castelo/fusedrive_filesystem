import json
import os
import time
from unittest.mock import MagicMock
import pytest

from src.infrastructure.drive.upload_manager import UploadManager
from src.monitoring.metrics.metrics import MetricsRegistry


def test_upload_manager_enqueue_and_process(tmp_path):
    storage_mock = MagicMock()
    dispatcher_mock = MagicMock()
    metrics = MetricsRegistry()

    # Executa a função na mesma thread para facilitar o teste
    def mock_submit(pool, func, *args, **kwargs):
        func(*args, **kwargs)

    dispatcher_mock.submit.side_effect = mock_submit

    cache_dir = str(tmp_path)
    manager = UploadManager(storage_mock, dispatcher_mock, metrics, cache_dir=cache_dir)

    # Criar um arquivo temporário fictício
    temp_file = os.path.join(cache_dir, "temp.txt")
    with open(temp_file, "w") as f:
        f.write("test_content")

    # Enqueue (vai chamar submit pro process_queue e depois pra do_upload localmente)
    manager.enqueue_file_for_upload("file_123", temp_file)

    # Como o mock_submit rodou de forma síncrona, a storage_mock já deve ter sido chamada
    storage_mock.upload_local_file_to_drive.assert_called_once()
    assert storage_mock.upload_local_file_to_drive.call_args[0][0] == "file_123"

    # Verifica que o arquivo temporário inicial foi deletado/movido
    assert not os.path.exists(temp_file)
    # Verifica que o arquivo copiado para o queue também foi limpo após o sucesso
    assert len(manager.queue) == 0
    assert metrics.get("upload_queue_size") == 0
    assert metrics.get("uploads") == 1


def test_upload_manager_retries_and_failure(tmp_path):
    storage_mock = MagicMock()
    dispatcher_mock = MagicMock()
    metrics = MetricsRegistry()

    # Storage falha sempre
    storage_mock.upload_local_file_to_drive.side_effect = Exception("Upload Error")

    def mock_submit(pool, func, *args, **kwargs):
        func(*args, **kwargs)

    dispatcher_mock.submit.side_effect = mock_submit

    cache_dir = str(tmp_path)
    # Reduzindo max_retries para 2 para testar
    manager = UploadManager(
        storage_mock, dispatcher_mock, metrics, cache_dir=cache_dir, max_retries=2
    )

    temp_file = os.path.join(cache_dir, "temp_fail.txt")
    with open(temp_file, "w") as f:
        f.write("fail_data")

    manager.enqueue_file_for_upload("file_fail", temp_file)

    # Foi chamado 1 vez inicialmente
    assert storage_mock.upload_local_file_to_drive.call_count == 1
    # Status deve estar pending e retries 1
    assert manager.queue["file_fail"]["retries"] == 1
    assert manager.queue["file_fail"]["status"] == "pending"
    assert metrics.get("upload_retries") == 1

    # Força a execução dos retries chamando execute_pending_upload_job manualmente (já que usamos threading.Timer na implementação real)
    manager.execute_pending_upload_job("file_fail")  # tentativa 2
    assert manager.queue["file_fail"]["retries"] == 2

    manager.execute_pending_upload_job("file_fail")  # tentativa 3 (excede limite)

    # Agora deve estar como failed
    assert manager.queue["file_fail"]["status"] == "failed"
    assert metrics.get("upload_failures") == 1

    # Falhados não contam no queue size para métricas ativas
    assert metrics.get("upload_queue_size") == 0


def test_upload_manager_persistence(tmp_path):
    storage_mock = MagicMock()
    dispatcher_mock = MagicMock()
    metrics = MetricsRegistry()
    cache_dir = str(tmp_path)

    # Criamos um json de queue "zumbi" (de uma execução que supostamente crashou)
    uploads_dir = os.path.join(cache_dir, "uploads")
    os.makedirs(uploads_dir, exist_ok=True)
    fake_path = os.path.join(uploads_dir, "fake.tmp")
    with open(fake_path, "w") as f:
        f.write("zombie_data")

    queue_data = {"file_zombie": {"path": fake_path, "retries": 1, "status": "pending"}}
    with open(os.path.join(uploads_dir, "queue.json"), "w") as f:
        json.dump(queue_data, f)

    # Quando inicializar, he deve carregar a fila existente
    manager = UploadManager(storage_mock, dispatcher_mock, metrics, cache_dir=cache_dir)

    assert "file_zombie" in manager.queue
    assert manager.queue["file_zombie"]["retries"] == 1

    # E como _process_queue é chamado no init, dispatcher deve ter sido invocado
    dispatcher_mock.submit.assert_called_with(
        "upload", manager.execute_pending_upload_job, "file_zombie"
    )

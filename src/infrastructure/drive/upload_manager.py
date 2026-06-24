import json
import logging
import os
import shutil
import threading
from typing import Dict, List, Optional
import time

from src.domain.contracts.interfaces import IStorageClient
from src.infrastructure.concurrency.dispatcher import RequestDispatcher
from src.monitoring.metrics.metrics import MetricsRegistry

logger = logging.getLogger("upload_manager")


class UploadManager:
    def __init__(
        self,
        storage: IStorageClient,
        dispatcher: RequestDispatcher,
        metrics: MetricsRegistry,
        cache_dir: str = ".cache",
        max_retries: int = 5,
    ):
        self.storage = storage
        self.dispatcher = dispatcher
        self.metrics = metrics
        self.max_retries = max_retries

        self.uploads_dir = os.path.join(cache_dir, "uploads")
        self.journal_dir = os.path.join(cache_dir, "journal")
        self.queue_file = os.path.join(self.uploads_dir, "queue.json")
        self.lock = threading.RLock()

        self.metrics.set("upload_queue_size", 0)
        self.metrics.set("upload_retries", 0)
        self.metrics.set("upload_failures", 0)

        os.makedirs(self.uploads_dir, exist_ok=True)
        os.makedirs(self.journal_dir, exist_ok=True)

        self.queue: Dict[str, dict] = {}
        self.load_upload_queue_from_disk()

        self._recover_journal()

        if self.queue:
            logger.info("Found %d pending uploads. Resuming...", len(self.queue))
            self._process_queue()

    def _recover_journal(self):
        """Varre o diretório journal por arquivos huérfanos que não foram enfileirados devido a crash."""
        if not os.path.exists(self.journal_dir):
            return

        for filename in os.listdir(self.journal_dir):
            filepath = os.path.join(self.journal_dir, filename)
            if not os.path.isfile(filepath):
                continue

            import re

            edit_match = re.match(r"^edit_([^_]+)_", filename)
            if edit_match:
                file_id = edit_match.group(1)
                logger.info("Recovering orphaned edit journal for %s", file_id)
                self.enqueue_file_for_upload(file_id, filepath)
                continue

            create_match = re.match(r"^create_([^_]+)_([^_]+)_", filename)
            if create_match:
                parent_id = create_match.group(1)
                import base64
                import uuid

                try:
                    name = base64.urlsafe_b64decode(
                        create_match.group(2).encode("utf-8")
                    ).decode("utf-8")
                    fake_id = "rec_" + str(uuid.uuid4())
                    logger.info(
                        "Recovering orphaned create journal for %s (parent %s)",
                        name,
                        parent_id,
                    )
                    self.enqueue_file_for_upload(
                        fake_id, filepath, is_new=True, parent_id=parent_id, name=name
                    )
                except Exception as error:
                    logger.error(
                        "Failed to decode orphaned create journal %s: %s",
                        filename,
                        error,
                    )

    def load_upload_queue_from_disk(self):
        with self.lock:
            if os.path.exists(self.queue_file):
                try:
                    with open(self.queue_file, "r") as f:
                        self.queue = json.load(f)
                except Exception as error:
                    logger.error("Failed to load upload queue: %s", error)
                    self.queue = {}
            self.metrics.set(
                "upload_queue_size",
                len([q for q in self.queue.values() if q["status"] != "failed"]),
            )

    def persist_upload_queue_to_disk(self):
        with self.lock:
            try:

                temp_queue_file = self.queue_file + ".tmp"
                with open(temp_queue_file, "w") as f:
                    json.dump(self.queue, f, indent=2)
                os.replace(temp_queue_file, self.queue_file)
                self.metrics.set(
                    "upload_queue_size",
                    len([q for q in self.queue.values() if q["status"] != "failed"]),
                )
            except Exception as error:
                logger.error("Failed to save upload queue: %s", error)

    def enqueue_file_for_upload(
        self,
        file_id: str,
        temp_path: str,
        is_new: bool = False,
        parent_id: Optional[str] = None,
        name: Optional[str] = None,
    ):
        with self.lock:
            safe_path = os.path.join(
                self.uploads_dir, f"{file_id }_{int (time .time ())}.tmp"
            )

            existing_retries = 0
            if file_id in self.queue:
                old_path = self.queue[file_id].get("path")
                existing_retries = self.queue[file_id].get("retries", 0)
                if old_path and os.path.exists(old_path):
                    try:
                        os.remove(old_path)
                    except OSError:
                        pass

            shutil.move(temp_path, safe_path)

            self.queue[file_id] = {
                "path": safe_path,
                "retries": existing_retries,
                "status": "pending",
                "job_type": "create" if is_new else "update",
                "parent_id": parent_id,
                "name": name,
            }
            self.persist_upload_queue_to_disk()

            logger.info(
                "Enqueued %s upload for %s (retries=%d)",
                self.queue[file_id]["job_type"],
                file_id,
                existing_retries,
            )

        self.dispatcher.submit("upload", self.execute_pending_upload_job, file_id)

    def _process_queue(self):
        with self.lock:
            for file_id, job in self.queue.items():
                if job["status"] == "pending":
                    self.dispatcher.submit(
                        "upload", self.execute_pending_upload_job, file_id
                    )

    def get_pending_path(self, file_id: str) -> Optional[str]:
        with self.lock:
            if file_id in self.queue:
                return self.queue[file_id].get("path")
            return None

    def execute_pending_upload_job(self, file_id: str):
        with self.lock:
            job = self.queue.get(file_id)
            if not job or job["status"] != "pending":
                return
            local_path = job["path"]
            retries = job["retries"]
            job_type = job.get("job_type", "update")

        if not os.path.exists(local_path):
            logger.error(
                "Local path %s missing for file_id %s. Removing from queue.",
                local_path,
                file_id,
            )
            self._remove_job(file_id)
            return

        try:
            logger.info(
                "Uploading %s (retry %d, type %s)...", file_id, retries, job_type
            )

            if job_type == "create":

                with open(local_path, "rb") as f:
                    content = f.read()

                node_metadata = self.storage.upload_new_file_to_drive(
                    job["parent_id"], job["name"], content
                )

                logger.info(
                    "Upload of %s (create) finished. Real ID: %s",
                    file_id,
                    node_metadata.file_id,
                )
            else:
                self.storage.upload_local_file_to_drive(file_id, local_path)
                logger.info("Upload of %s finished.", file_id)

            self.metrics.inc("uploads")
            self._remove_job(file_id, local_path)
        except Exception as error:
            from tenacity import RetryError

            real_err = error
            if (
                isinstance(error, RetryError)
                and error.last_attempt
                and error.last_attempt.exception()
            ):
                real_err = error.last_attempt.exception()

            logger.error("Error uploading %s: %s", file_id, real_err)
            if "storageQuotaExceeded" in str(real_err):
                from src.infrastructure.drive.circuit_breaker import (
                    GoogleDriveQuotaCircuitBreaker,
                )

                GoogleDriveQuotaCircuitBreaker().trip()
                self._handle_failure(file_id, is_fatal=True)
            else:
                self._handle_failure(file_id)

    def _remove_job(self, file_id: str, local_path: Optional[str] = None):
        with self.lock:
            if local_path and os.path.exists(local_path):
                try:
                    os.remove(local_path)
                except OSError:
                    pass
            self.queue.pop(file_id, None)
            self.persist_upload_queue_to_disk()

    def _handle_failure(self, file_id: str, is_fatal: bool = False):
        with self.lock:
            job = self.queue.get(file_id)
            if not job:
                return

            job["retries"] += 1
            self.metrics.inc("upload_retries")

            if job["retries"] > self.max_retries or is_fatal:
                logger.critical(
                    "File %s failed (fatal=%s). Marking as failed.", file_id, is_fatal
                )
                job["status"] = "failed"
                self.metrics.inc("upload_failures")
                self.persist_upload_queue_to_disk()
            else:
                self.persist_upload_queue_to_disk()
                backoff = 2 ** job["retries"]
                logger.info("Scheduling retry for %s in %ds", file_id, backoff)

                def _retry():
                    try:
                        self.dispatcher.submit(
                            "upload", self.execute_pending_upload_job, file_id
                        )
                    except RuntimeError:
                        logger.info(
                            "Upload retry for %s cancelled: dispatcher is shutting down",
                            file_id,
                        )

                timer = threading.Timer(backoff, _retry)
                timer.daemon = True
                timer.start()

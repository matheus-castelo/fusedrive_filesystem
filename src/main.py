import os
import signal
import sys
import time

from dotenv import load_dotenv

from fuse import FUSE
from src.fuse.operations.fuse_ops import FuseOps
from src.infrastructure.cache.memory_cache import MemoryMetadataCache
from src.infrastructure.drive.drive_client import GoogleDriveStorageClient
from src.monitoring.logging.logger import setup_json_logger
from src.monitoring.metrics.metrics import MetricsRegistry
from src.infrastructure.concurrency.dispatcher import RequestDispatcher

load_dotenv()

logger = setup_json_logger("main")


def force_unmount_fuse_point(mountpoint: str):
    logger.info("Desmontando %s...", mountpoint)
    os.system(
        f"fusermount3 -u {mountpoint } 2>/dev/null || fusermount -u {mountpoint } 2>/dev/null"
    )


def main():
    mountpoint = os.getenv("DRIVE_MOUNT_DIR") or (
        sys.argv[1] if len(sys.argv) > 1 else None
    )
    credentials_path = os.getenv("DRIVE_CREDENTIALS") or (
        sys.argv[2] if len(sys.argv) > 2 else None
    )
    root_id = os.getenv("DRIVE_FOLDER_ID") or (
        sys.argv[3] if len(sys.argv) > 3 else "root"
    )

    if not mountpoint or not credentials_path:
        print("Uso: python -m src.main [mount_dir] [credentials.json] [folder_id]")
        print(
            "Ou configure via .env: DRIVE_MOUNT_DIR, DRIVE_CREDENTIALS, DRIVE_FOLDER_ID"
        )
        sys.exit(1)

    force_unmount_fuse_point(mountpoint)
    time.sleep(1)

    if not os.path.exists(credentials_path):
        logger.error("Credenciais nao encontradas: %s", credentials_path)
        sys.exit(1)

    os.makedirs(mountpoint, exist_ok=True)

    storage = GoogleDriveStorageClient(credentials_path)
    cache = MemoryMetadataCache()
    metrics = MetricsRegistry()
    dispatcher = RequestDispatcher(metrics)
    fuse_ops = FuseOps(
        storage=storage, cache=cache, dispatcher=dispatcher, root_id=root_id
    )

    logger.info("Montando Google Drive em %s (root=%s)", mountpoint, root_id)
    logger.info("Ctrl+C para desmontar")

    uid = int(os.getenv("PUID", 1000))
    gid = int(os.getenv("PGID", 1000))
    allow_other = os.getenv("FUSE_ALLOW_OTHER", "0") == "1"

    try:
        FUSE(
            fuse_ops,
            mountpoint,
            nothreads=False,
            foreground=True,
            allow_other=allow_other,
            uid=uid,
            gid=gid,
        )
    except KeyboardInterrupt:
        logger.info("KeyboardInterrupt detectado. Encerrando...")
    except RuntimeError as error:
        logger.error("Erro FUSE: %s", error)
    finally:
        dispatcher.shutdown()
        force_unmount_fuse_point(mountpoint)
        logger.info("Encerrado.")


if __name__ == "__main__":
    main()

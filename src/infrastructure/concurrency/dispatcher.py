from concurrent.futures import ThreadPoolExecutor, Future
from typing import Callable
from src.monitoring.metrics.metrics import MetricsRegistry


class RequestDispatcher:
    def __init__(
        self,
        metrics: MetricsRegistry,
        read_workers=8,
        write_workers=4,
        meta_workers=4,
        prefetch_workers=4,
    ):
        self.metrics = metrics

        self.pools = {
            "read": ThreadPoolExecutor(
                max_workers=read_workers, thread_name_prefix="read"
            ),
            "prefetch": ThreadPoolExecutor(
                max_workers=prefetch_workers, thread_name_prefix="prefetch"
            ),
            "write": ThreadPoolExecutor(
                max_workers=write_workers, thread_name_prefix="write"
            ),
            "metadata": ThreadPoolExecutor(
                max_workers=meta_workers, thread_name_prefix="meta"
            ),
            "upload": ThreadPoolExecutor(max_workers=2, thread_name_prefix="upload"),
        }

        for pool_name in self.pools:
            self.metrics.set(f"pool_{pool_name }_active", 0)
            self.metrics.set(f"pool_{pool_name }_queue", 0)

    def submit(self, pool_name: str, fn: Callable, *args, **kwargs) -> Future:
        if pool_name not in self.pools:
            raise ValueError(f"Pool {pool_name } inexistente.")

        self.metrics.inc("thread_pool_tasks")
        return self.pools[pool_name].submit(fn, *args, **kwargs)

    def update_metrics(self):
        """Atualiza o painel de fila no metrics analisando os executors internamente."""
        for name, executor in self.pools.items():

            if hasattr(executor, "_work_queue"):
                qsize = executor._work_queue.qsize()
                self.metrics.set(f"pool_{name }_queue", qsize)
            if hasattr(executor, "_threads"):

                active = len(executor._threads)
                self.metrics.set(f"pool_{name }_active", active)

    def shutdown(self, wait=True):
        for pool in self.pools.values():
            pool.shutdown(wait=wait)

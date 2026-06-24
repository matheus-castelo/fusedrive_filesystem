import threading


class MetricsRegistry:
    _instance = None
    _lock = threading.Lock()

    def __init__(self):

        if not hasattr(self, "_stats"):
            self.metrics = {}
            self._stats = self.metrics

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(MetricsRegistry, cls).__new__(cls)
        return cls._instance

    def reset(self):
        with self._lock:
            self._stats = {}

    def inc(self, key: str):
        self.add(key, 1)

    def add(self, key: str, value: int):
        with self._lock:
            if key not in self._stats:
                self._stats[key] = 0
            self._stats[key] += value

    def get_stats(self) -> dict:
        with self._lock:
            return self._stats.copy()

    def set(self, key: str, value: int):
        with self._lock:
            self._stats[key] = value

    def get(self, key: str) -> int:
        with self._lock:
            return self._stats.get(key, 0)

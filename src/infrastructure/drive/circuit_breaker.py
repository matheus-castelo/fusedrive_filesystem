import threading


class GoogleDriveQuotaCircuitBreaker:
    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(GoogleDriveQuotaCircuitBreaker, cls).__new__(cls)
                cls._instance.is_tripped = False
        return cls._instance

    def trip(self):
        """Ativa o disjuntor (cota estourada)."""
        with self._lock:
            self.is_tripped = True

    def reset(self):
        """Desativa o disjuntor (cota livre)."""
        with self._lock:
            self.is_tripped = False

    def is_quota_exceeded(self) -> bool:
        """Verifica se a cota está estourada."""
        with self._lock:
            return self.is_tripped

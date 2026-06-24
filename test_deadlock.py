import time
import threading
from concurrent.futures import Future

from src.infrastructure.concurrency.dispatcher import RequestDispatcher
from src.infrastructure.cache.chunk_manager import ChunkManager
from src.monitoring.metrics.metrics import MetricsRegistry
from src.domain.contracts.interfaces import IStorageClient

class MockStorage(IStorageClient):
    def get_file_chunk(self, file_id: str, start: int, end: int) -> bytes:
        # Simulate network latency
        time.sleep(1.0)
        return b"x" * (end - start + 1)
        
    def list_children(self, parent_id): pass
    def get_file_content(self, file_id): pass
    def create_file(self, parent_id, name, content): pass
    def create_folder(self, parent_id, name): pass
    def delete_file(self, file_id): pass
    def update_file(self, file_id, path): pass

def run_test():
    metrics = MetricsRegistry()
    dispatcher = RequestDispatcher(metrics, read_workers=2) # 2 workers to easily show exhaustion
    storage = MockStorage()
    
    # 5MB chunks
    cm = ChunkManager(storage, chunk_size=5*1024*1024, max_chunks=20, cache_dir="/tmp/test_cache", dispatcher=dispatcher, metrics=metrics)
    
    file_id = "test_file"
    total_size = 100 * 1024 * 1024 # 100MB
    
    print("Simulating Dolphin/Haruna reading...")
    
    def read_thread(offset, length):
        print(f"Reading offset={offset}, length={length}...")
        start_time = time.time()
        data = cm.get_data(file_id, offset, length, total_size, fh=1)
        print(f"Read done in {time.time() - start_time:.2f}s for offset={offset}")

    # Dolphin reads start of file
    t1 = threading.Thread(target=read_thread, args=(0, 1024))
    t1.start()
    
    time.sleep(0.1)
    
    # Dolphin starts reading another chunk concurrently
    t2 = threading.Thread(target=read_thread, args=(10*1024*1024, 1024))
    t2.start()

    time.sleep(0.1)

    # Dolphin seeks to end of file to read MOOV atom
    t3 = threading.Thread(target=read_thread, args=(90*1024*1024, 1024))
    t3.start()

    t1.join()
    t2.join()
    t3.join()
    
    print("Test finished.")
    dispatcher.shutdown(wait=False)

if __name__ == "__main__":
    run_test()

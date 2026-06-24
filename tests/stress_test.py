import concurrent.futures
import os
import random
import time
import sys

MOUNT_DIR = "/home/castle/FuseDriveFilesystem"
NUM_FILES = 20
FILE_SIZE = 512 * 1024  # 512 KB


def create_and_write(file_id):
    path = os.path.join(MOUNT_DIR, f"stress_{file_id}.bin")
    data = os.urandom(FILE_SIZE)
    print(f"[{file_id}] Writing {FILE_SIZE} bytes to {path}")

    start_time = time.time()
    with open(path, "wb") as f:
        f.write(data)
    duration = time.time() - start_time
    print(f"[{file_id}] Write completed in {duration:.2f}s")
    return path


def read_file(path):
    print(f"Reading from {path}")
    start_time = time.time()
    with open(path, "rb") as f:
        data = f.read()
    duration = time.time() - start_time
    assert len(data) == FILE_SIZE
    print(f"Read {len(data)} bytes from {path} in {duration:.2f}s")


def delete_file(path):
    print(f"Deleting {path}")
    os.remove(path)


def main():
    if not os.path.ismount(MOUNT_DIR):
        print(f"ERROR: {MOUNT_DIR} is not mounted.")
        sys.exit(1)

    print(f"Starting Stress Test on {MOUNT_DIR}...")

    # 1. Escritas concorrentes
    paths = []
    print("\n--- PHASE 1: CONCURRENT WRITES ---")
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        futures = [executor.submit(create_and_write, i) for i in range(NUM_FILES)]
        for f in concurrent.futures.as_completed(futures):
            paths.append(f.result())

    # 2. Leituras concorrentes instantâneas (deve pegar da Fila Local graças ao Read-After-Write)
    print("\n--- PHASE 2: CONCURRENT READ-AFTER-WRITE ---")
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        futures = [executor.submit(read_file, path) for path in paths]
        concurrent.futures.wait(futures)

    # 3. Esperar uploads
    print("\n--- PHASE 3: WAITING FOR UPLOADS TO COMPLETE ---")
    print("Wait 15 seconds to allow background queue to process some uploads...")
    time.sleep(15)

    # 4. Leituras após algum tempo
    print("\n--- PHASE 4: CONCURRENT READS LATER ---")
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        futures = [executor.submit(read_file, path) for path in paths]
        concurrent.futures.wait(futures)

    # 5. Deleções
    # print("\n--- PHASE 5: CLEANUP ---")
    # with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
    #    futures = [executor.submit(delete_file, path) for path in paths]
    #    concurrent.futures.wait(futures)

    print("\nSTRESS TEST COMPLETED SUCCESSFULLY.")


if __name__ == "__main__":
    main()

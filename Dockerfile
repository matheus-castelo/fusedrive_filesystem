FROM python:3.12-slim

RUN apt-get update && \
    apt-get install -y --no-install-recommends fuse3 libfuse2 && \
    sed -i 's/#user_allow_other/user_allow_other/' /etc/fuse.conf && \
    echo "user_allow_other" >> /etc/fuse.conf && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src/ src/

RUN mkdir -p /mnt/drive

ENV PYTHONPATH=/app
ENV DRIVE_MOUNT_DIR=/mnt/drive
ENV DRIVE_CREDENTIALS=/app/credentials.json
ENV DRIVE_FOLDER_ID=root

CMD ["python", "-m", "src.main"]

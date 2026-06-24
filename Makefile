.PHONY: up down build restart clean
clean:
	@echo "Limpando mounts zumbis..."
	@fusermount3 -u -z mount_dir 2>/dev/null || true
	@sudo umount -l mount_dir 2>/dev/null || true

build: clean
	docker compose build --no-cache

up: clean
	docker compose up -d

down: clean
	docker compose down

restart: clean
	docker compose restart

setup:
	@echo "Criando ambiente virtual e instalando dependencias..."
	uv venv --allow-existing
	uv pip install -r requirements.txt

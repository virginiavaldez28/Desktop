#!/bin/sh
# Copia de seguridad de la base de datos. Uso: ./scripts/backup.sh
# Deja un archivo backups/valpob-AAAA-MM-DD_HHMM.sql.gz. Conviene programarlo todos los días
# (cron) y copiar la carpeta "backups" a otro lugar (Google Drive, disco externo, etc.).
set -e
cd "$(dirname "$0")/.."
mkdir -p backups
ARCHIVO="backups/valpob-$(date +%Y-%m-%d_%H%M).sql.gz"
docker compose exec -T db pg_dump -U valpob valpob | gzip > "$ARCHIVO"
echo "Copia guardada en $ARCHIVO"

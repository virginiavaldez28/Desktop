#!/bin/sh
# Restaura una copia de seguridad. Uso: ./scripts/restaurar.sh backups/valpob-2026-09-25_2300.sql.gz
# ATENCIÓN: reemplaza TODOS los datos actuales por los de la copia.
set -e
cd "$(dirname "$0")/.."
if [ -z "$1" ]; then echo "Indicá el archivo de la copia."; exit 1; fi
printf "Esto borra los datos actuales y los reemplaza por %s. ¿Seguir? (si/no) " "$1"
read RESPUESTA
[ "$RESPUESTA" = "si" ] || exit 1
docker compose exec -T db psql -U valpob -d postgres -c "DROP DATABASE valpob WITH (FORCE);" -c "CREATE DATABASE valpob OWNER valpob;"
gunzip -c "$1" | docker compose exec -T db psql -U valpob valpob
echo "Copia restaurada."

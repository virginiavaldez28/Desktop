#!/bin/bash
# Carga la información de Junio a Agosto 2026 en la aplicación publicada.
# Antes, subí estos archivos a la carpeta ~/datos (pestaña Files de PythonAnywhere):
#   Valpob_Punto_Equilibrio_Rentabilidad.xlsx, ventas07.xlsx, ventas08.xlsx,
#   Compras_Julio_2026_v2.xlsx, Compras_Agosto_2026.xlsx
# Uso: bash deploy/pythonanywhere_cargar_datos.sh
set -e
cd "$(dirname "$0")/.."
D="$HOME/datos"
PY="$HOME/.virtualenvs/valpob/bin/python"
set -a; source .env; set +a
"$PY" manage.py importar_excel "$D/Valpob_Punto_Equilibrio_Rentabilidad.xlsx" --anio 2026 --desde-mes 6 --reemplazar
"$PY" manage.py completar_iva_ventas "$D/ventas07.xlsx" "$D/ventas08.xlsx"
"$PY" manage.py importar_compras "$D/Compras_Julio_2026_v2.xlsx" --anio 2026 --mes 7 --reemplazar
"$PY" manage.py importar_compras "$D/Compras_Agosto_2026.xlsx" --anio 2026 --mes 8 --reemplazar
echo "Datos cargados. Podés borrar la carpeta ~/datos si querés: la información ya está en la base."

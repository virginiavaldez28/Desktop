#!/bin/bash
# Instala la aplicación en PythonAnywhere (plan gratuito).
# Uso, desde una consola Bash de PythonAnywhere, dentro de la carpeta del proyecto:
#     bash deploy/pythonanywhere_instalar.sh
set -e
cd "$(dirname "$0")/.."
PROYECTO="$(pwd)"
DOMINIO="${USER}.pythonanywhere.com"
VENV="$HOME/.virtualenvs/valpob"

echo "== 1/4 Entorno de Python"
if [ ! -d "$VENV" ]; then
    python3.11 -m venv "$VENV"
fi
"$VENV/bin/pip" install --quiet --upgrade pip
"$VENV/bin/pip" install --quiet -r requirements.txt

echo "== 2/4 Configuración (archivo .env, no se sube a GitHub)"
if [ ! -f .env ]; then
    CLAVE="$("$VENV/bin/python" -c 'import secrets; print(secrets.token_urlsafe(50))')"
    cat > .env <<CONF
SECRET_KEY=$CLAVE
DEBUG=0
ALLOWED_HOSTS=$DOMINIO
CSRF_TRUSTED_ORIGINS=https://$DOMINIO
CONF
fi
set -a; source .env; set +a

echo "== 3/4 Base de datos y archivos estáticos"
"$VENV/bin/python" manage.py migrate --noinput
"$VENV/bin/python" manage.py collectstatic --noinput >/dev/null

echo "== 4/4 Listo. Datos para la pestaña Web:"
echo "   Source code:      $PROYECTO"
echo "   Working directory: $PROYECTO"
echo "   Virtualenv:       $VENV"
echo "   Static files:     URL /static/  ->  Directory $PROYECTO/staticfiles"
echo
echo "   Reemplazá TODO el contenido del archivo WSGI por esto:"
echo "------------------------------------------------------------"
cat <<WSGI
import os, sys
PROYECTO = "$PROYECTO"
sys.path.insert(0, PROYECTO)
for linea in open(os.path.join(PROYECTO, ".env")):
    if "=" in linea:
        clave, valor = linea.strip().split("=", 1)
        os.environ.setdefault(clave, valor)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "valpob.settings")
from django.core.wsgi import get_wsgi_application
application = get_wsgi_application()
WSGI
echo "------------------------------------------------------------"

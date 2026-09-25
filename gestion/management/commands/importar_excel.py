from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from gestion.excel import ErrorExcel, leer_excel
from gestion.importacion import ErrorImportacion, importar


class Command(BaseCommand):
    help = (
        "Carga inicial: importa Personal y Nómina, Registro de Ventas, Registro de Compras, "
        "los gastos cargados a mano de Apertura y los Gastos Bancarios desde el Excel original."
    )

    def add_arguments(self, parser):
        parser.add_argument("archivo", help="Ruta al Excel (.xlsx).")
        parser.add_argument("--anio", type=int, default=2026, help="Año de los meses del Excel (por defecto 2026).")
        parser.add_argument(
            "--incluir-ejemplos", action="store_true",
            help='Importa también los renglones marcados "Ejemplo (reemplazar)". Por defecto se omiten.',
        )
        parser.add_argument(
            "--reemplazar", action="store_true",
            help="Si los meses ya tienen datos, los borra y vuelve a importar.",
        )
        parser.add_argument("--usuario", help="Usuario que figura como autor de la carga.")

    def handle(self, *args, **opciones):
        usuario = None
        if opciones["usuario"]:
            usuario = get_user_model().objects.filter(username=opciones["usuario"]).first()
            if usuario is None:
                raise CommandError(f"No existe el usuario {opciones['usuario']!r}.")
        try:
            contenido = leer_excel(opciones["archivo"])
            resumen = importar(
                contenido, opciones["anio"], usuario=usuario,
                incluir_ejemplos=opciones["incluir_ejemplos"], reemplazar=opciones["reemplazar"],
            )
        except (ErrorExcel, ErrorImportacion) as error:
            raise CommandError(str(error)) from error
        self.stdout.write(self.style.SUCCESS("Importación terminada:"))
        for clave, cantidad in resumen.items():
            self.stdout.write(f"  {clave}: {cantidad}")

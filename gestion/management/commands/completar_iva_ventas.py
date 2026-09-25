from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from gestion.catalogos import MES_POR_NOMBRE
from gestion.formato import moneda
from gestion.models import Periodo
from gestion.ventas_origen import completar, leer


class Command(BaseCommand):
    help = (
        "Completa neto e IVA de las facturas de venta ya cargadas, a partir del listado del sistema "
        "de facturación (ej. Julio_ventas.xlsx). Se puede pasar más de un archivo."
    )

    def add_arguments(self, parser):
        parser.add_argument("archivos", nargs="+")
        parser.add_argument("--usuario", help="Usuario que figura como autor de la modificación.")

    def handle(self, *args, **opciones):
        usuario = None
        if opciones["usuario"]:
            usuario = get_user_model().objects.filter(username=opciones["usuario"]).first()
            if usuario is None:
                raise CommandError(f"No existe el usuario {opciones['usuario']!r}.")
        comprobantes = [c for ruta in opciones["archivos"] for c in leer(ruta)]
        r = completar(comprobantes, usuario=usuario)
        self.stdout.write(self.style.SUCCESS(f"Facturas actualizadas con neto e IVA: {r.actualizadas}"))
        for venta, antes, despues in r.neto_corregido:
            self.stdout.write(self.style.WARNING(
                f"  Neto corregido: {venta} — antes {moneda(antes)}, ahora {moneda(despues)} "
                f"(el importe anterior incluía IVA)"
            ))
        for c in r.no_encontradas_en_app:
            self.stdout.write(self.style.ERROR(
                f"  Está en el archivo pero no en la aplicación: {c.tipo} {c.punto_venta}-{c.numero} {c.cliente}"
            ))
        meses = {v.periodo for v in r.sin_datos_en_archivo}
        for periodo in sorted(meses, key=lambda p: (p.anio, p.mes)):
            faltan = [v for v in r.sin_datos_en_archivo if v.periodo == periodo]
            self.stdout.write(f"  {periodo}: {len(faltan)} facturas sin datos en los archivos (quedan con IVA en 0).")

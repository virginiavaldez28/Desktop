"""Carga las facturas de compra de un mes desde la planilla de revisión.

La planilla tiene una fila por factura con los datos del sistema de compras y,
en las columnas "Categoría final" y "Servicio Asignado final", la clasificación
revisada. Las filas cuya categoría empieza con "EXCLUIR" no se cargan.
"""
from collections import Counter
from datetime import date, datetime

import openpyxl
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from gestion.catalogos import CategoriaCompra, ServicioCompra
from gestion.excel import decimal, texto
from gestion.formato import moneda
from gestion.models import Compra, Periodo, Proveedor

CATEGORIAS = {c.label: c for c in CategoriaCompra}
SERVICIOS = {s.label: s for s in ServicioCompra}
TIPOS = {"FC": "Factura", "FCE": "Factura de Crédito Electrónica", "REC": "Recibo", "NC": "Nota de Crédito",
         "NCE": "N.C. Electrónica", "ND": "Nota de Débito"}


class Command(BaseCommand):
    help = "Carga las facturas de compra de un mes desde la planilla de revisión (columnas \"… final\")."

    def add_arguments(self, parser):
        parser.add_argument("archivo")
        parser.add_argument("--anio", type=int, required=True)
        parser.add_argument("--mes", type=int, required=True)
        parser.add_argument("--reemplazar", action="store_true", help="Borra antes las compras ya cargadas de ese mes.")
        parser.add_argument("--usuario")

    def handle(self, *args, **o):
        usuario = None
        if o["usuario"]:
            usuario = get_user_model().objects.filter(username=o["usuario"]).first()
            if usuario is None:
                raise CommandError(f"No existe el usuario {o['usuario']!r}.")
        periodo = Periodo.objects.filter(anio=o["anio"], mes=o["mes"]).first()
        if periodo is None:
            raise CommandError(f"No existe el período {o['mes']}/{o['anio']}. Creálo primero en Períodos (meses).")

        libro = openpyxl.load_workbook(o["archivo"], data_only=True)
        hoja = next((h for h in libro.worksheets if any(c.value == "Categoría final" for c in h[1])), None)
        if hoja is None:
            raise CommandError('No encontré una hoja con la columna "Categoría final".')
        col = {texto(c.value): c.column - 1 for c in hoja[1] if c.value}

        compras, excluidas, errores = [], 0, []
        for n, fila in enumerate(hoja.iter_rows(min_row=2, values_only=True), start=2):
            if not fila[col["Proveedor"]]:
                continue
            categoria = texto(fila[col["Categoría final"]])
            if categoria.startswith("EXCLUIR"):
                excluidas += 1
                continue
            servicio = texto(fila[col["Servicio Asignado final"]])
            if categoria not in CATEGORIAS or servicio not in SERVICIOS:
                errores.append(f"Fila {n}: categoría {categoria!r} o servicio {servicio!r} desconocido.")
                continue
            fecha = fila[col["Fecha"]]
            fecha = fecha.date() if isinstance(fecha, datetime) else fecha
            if not isinstance(fecha, date):
                errores.append(f"Fila {n}: fecha inválida {fecha!r}.")
                continue
            tipo = texto(fila[col["Tipo"]])
            observaciones = " ".join(
                texto(fila[col[c]]) for c in ("Motivo / pregunta", "observacion de virginia") if c in col
            ).strip()
            compras.append(dict(
                fila=n,
                proveedor=texto(fila[col["Proveedor"]]),
                fecha=fecha,
                tipo_comprobante=f"{TIPOS.get(tipo, tipo)} {texto(fila[col['Letra']])}".strip(),
                punto_venta=int(fila[col["PV"]] or 0),
                numero=int(fila[col["N°"]] or 0),
                categoria=CATEGORIAS[categoria],
                servicio_asignado=SERVICIOS[servicio],
                neto=decimal(fila[col["Monto sin IVA"]]),
                iva=decimal(fila[col["IVA"]]),
                observaciones=observaciones,
            ))
        if errores:
            raise CommandError("No se cargó nada. Errores:\n" + "\n".join(errores))

        auditoria = {"creado_por": usuario, "modificado_por": usuario}
        with transaction.atomic():
            if periodo.compras.exists():
                if not o["reemplazar"]:
                    raise CommandError(f"{periodo} ya tiene compras cargadas. Usá --reemplazar para reemplazarlas.")
                periodo.compras.all().delete()
            for c in compras:
                fila = c.pop("fila")
                c["proveedor"], _ = Proveedor.objects.get_or_create(nombre=c["proveedor"], defaults=auditoria)
                compra = Compra(periodo=periodo, **c, **auditoria)
                try:
                    compra.full_clean()
                except Exception as error:
                    raise CommandError(f"Fila {fila}: {error}") from error
                compra.save()

        por_categoria = Counter()
        for c in compras:
            por_categoria[c["categoria"].label] += c["neto"]
        self.stdout.write(self.style.SUCCESS(f"{periodo}: {len(compras)} renglones cargados, {excluidas} facturas excluidas."))
        for categoria, total in por_categoria.most_common():
            self.stdout.write(f"  {categoria}: {moneda(total)} (sin IVA)")

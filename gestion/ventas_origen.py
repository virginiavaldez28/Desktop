"""Completa neto e IVA de las ventas a partir de los listados del sistema de facturación.

Los archivos "Julio_ventas.xlsx" / "agosto_ventas.xlsx" traen, por comprobante,
las columnas Total (neto), MontoIVA y Liquido (total con IVA). El Excel de
gestión sólo tenía un importe por factura; con este listado se guardan los dos.

En las facturas B el IVA viene incluido en el Total, así que el neto se toma
siempre como Liquido − MontoIVA (en las facturas A da lo mismo que Total).
"""
from dataclasses import dataclass, field
from decimal import Decimal

import openpyxl
from django.db import transaction

from .excel import decimal, texto
from .models import Venta

# TipoOper + Serie del sistema → Tipo de Comprobante del Registro de Ventas.
TIPOS = {
    ("FC", "A"): "Factura A",
    ("FC", "B"): "Factura B",
    ("FCE", "A"): "Fact. Créd. Electrónica A",
    ("NC", "A"): "Nota de Crédito A",
    ("NC", "B"): "Nota de Crédito B",
    ("NCE", "A"): "N.C. Electrónica A",
}


@dataclass
class Comprobante:
    tipo: str
    punto_venta: int
    numero: int
    cliente: str
    neto: Decimal
    iva: Decimal


@dataclass
class Resultado:
    actualizadas: int = 0
    neto_corregido: list = field(default_factory=list)  # (venta, neto anterior, neto nuevo)
    no_encontradas_en_app: list = field(default_factory=list)
    sin_datos_en_archivo: list = field(default_factory=list)


def leer(ruta):
    hoja = openpyxl.load_workbook(ruta, data_only=True).worksheets[0]
    col = {texto(c.value): c.column - 1 for c in hoja[1] if c.value}
    comprobantes = []
    for fila in hoja.iter_rows(min_row=2, values_only=True):
        if not fila[col["NumOper"]]:
            continue
        clave = (texto(fila[col["TipoOper"]]), texto(fila[col["Serie"]]))
        iva = decimal(fila[col["MontoIVA"]])
        liquido = decimal(fila[col["Liquido"]])
        comprobantes.append(Comprobante(
            tipo=TIPOS.get(clave, " ".join(clave)),
            punto_venta=int(fila[col["PVenta"]]),
            numero=int(fila[col["NumOper"]]),
            cliente=texto(fila[col["ContraparteC"]]),
            neto=liquido - iva,
            iva=iva,
        ))
    return comprobantes


@transaction.atomic
def completar(comprobantes, periodos=None, usuario=None):
    resultado = Resultado()
    ventas = Venta.objects.all()
    if periodos is not None:
        ventas = ventas.filter(periodo__in=periodos)
    por_clave = {(v.tipo_comprobante, v.punto_venta, v.numero): v for v in ventas}
    vistos = set()
    for c in comprobantes:
        clave = (c.tipo, c.punto_venta, c.numero)
        venta = por_clave.get(clave)
        if venta is None:
            resultado.no_encontradas_en_app.append(c)
            continue
        vistos.add(clave)
        if venta.neto != c.neto:
            resultado.neto_corregido.append((venta, venta.neto, c.neto))
        venta.neto, venta.iva = c.neto, c.iva
        venta.modificado_por = usuario
        venta.save()
        resultado.actualizadas += 1
    resultado.sin_datos_en_archivo = [v for k, v in por_clave.items() if k not in vistos]
    return resultado

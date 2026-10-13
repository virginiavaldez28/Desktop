"""Distribución por persona de los importes leídos de los documentos de nómina de un mes.

Cada grupo completa una columna de la nómina a partir de todos los documentos de ese tipo cargados
en el mes (por ejemplo, el F.931 de Valpob y el de Global se suman). Primero se muestra la propuesta
(valor actual y nuevo por persona) y recién al confirmar se graba; después todo sigue siendo editable.
"""
from collections import defaultdict
from dataclasses import dataclass, field
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from . import lectores
from .models import DocumentoNomina, LiquidacionNomina

CERO = Decimal("0")
TOLERANCIA = Decimal("1")
T = DocumentoNomina.Tipo

GRUPOS = {
    "contribuciones": {
        "titulo": "Contribuciones patronales (F.931)",
        "tipos": [T.F931],
        "campo": "contribuciones_patronales",
    },
    "haberes": {
        "titulo": "Haberes y 1ª quincena (recibos o Libro de Sueldos)",
        "tipos": [T.RECIBOS, T.LSD],
        "campo": "haberes",
    },
    "sindicato": {
        "titulo": "Sindicato y mutual — parte empresa (planillas sindicales)",
        "tipos": [T.SINDICATO_SPP, T.SINDICATO_JERARQUICOS, T.SINDICATO_UOCRA],
        "campo": "sindicato_mutual",
    },
}
GRUPO_DE_TIPO = {tipo: clave for clave, g in GRUPOS.items() for tipo in g["tipos"]}


def leer_documento(doc, texto=None):
    texto = texto if texto is not None else lectores.texto_pdf(doc.archivo.path)
    if doc.tipo == T.F931:
        return lectores.leer_f931(texto)
    if doc.tipo == T.RECIBOS:
        return lectores.leer_recibos(texto)
    if doc.tipo == T.LSD:
        return lectores.leer_lsd(texto, primera_quincena=doc.primera_quincena)
    if doc.tipo == T.SINDICATO_SPP:
        return lectores.leer_spp(texto, doc.intereses)
    if doc.tipo == T.SINDICATO_JERARQUICOS:
        return lectores.leer_jerarquicos(texto, doc.intereses)
    if doc.tipo == T.SINDICATO_UOCRA:
        return lectores.leer_uocra(texto, doc.intereses)
    raise lectores.ErrorLectura(f"Tipo de documento desconocido: {doc.tipo}")


@dataclass
class FilaPropuesta:
    persona: object
    cuil: str
    actual: Decimal
    nuevo: Decimal = None
    actual_del_mes: Decimal = CERO
    nuevo_del_mes: Decimal = None
    detalle: str = ""

    @property
    def cambia(self):
        # Diferencias de centavos entre documentos (redondeos) no se consideran cambios.
        if self.nuevo is None:
            return False
        if abs(self.nuevo - self.actual) >= TOLERANCIA:
            return True
        return self.nuevo_del_mes is not None and abs(self.nuevo_del_mes - self.actual_del_mes) >= TOLERANCIA

    @property
    def diferencia(self):
        return (self.nuevo - self.actual) if self.nuevo is not None else None


@dataclass
class Propuesta:
    grupo: str
    documentos: list
    filas: list = field(default_factory=list)
    sin_renglon: list = field(default_factory=list)  # (cuil, nombre, importe) que figuran en los documentos y no en la nómina
    errores: list = field(default_factory=list)
    avisos: list = field(default_factory=list)

    @property
    def titulo(self):
        return GRUPOS[self.grupo]["titulo"]

    @property
    def con_cambios(self):
        return [f for f in self.filas if f.cambia]

    @property
    def total_actual(self):
        return sum((f.actual for f in self.filas if f.nuevo is not None), CERO)

    @property
    def total_nuevo(self):
        return sum((f.nuevo for f in self.filas if f.nuevo is not None), CERO)


def propuesta(periodo, grupo):
    g = GRUPOS[grupo]
    documentos = list(DocumentoNomina.objects.filter(periodo=periodo, tipo__in=g["tipos"]).order_by("creado_en"))
    prop = Propuesta(grupo=grupo, documentos=documentos)
    if grupo == "haberes" and any(d.tipo == T.RECIBOS for d in documentos) and any(d.tipo == T.LSD for d in documentos):
        prop.avisos.append("Hay recibos y Libro de Sueldos del mismo mes: para la nómina se usan sólo los recibos (más abajo está el control cruzado entre los dos).")
        documentos = [d for d in documentos if d.tipo == T.RECIBOS]
    importes, del_mes, detalle, nombres = defaultdict(lambda: CERO), defaultdict(lambda: CERO), defaultdict(list), {}
    for doc in documentos:
        try:
            lectura = leer_documento(doc)
        except Exception as error:  # un PDF que no se puede leer no frena a los demás
            prop.errores.append(f"{doc.nombre_archivo}: {error}")
            continue
        for cuil, valor in lectura.importes.items():
            importes[cuil] += valor
            del_mes[cuil] += lectura.del_mes.get(cuil, CERO)
            detalle[cuil].append(lectura.detalle.get(cuil, ""))
            nombres.setdefault(cuil, lectura.nombres.get(cuil, ""))
    renglones = LiquidacionNomina.objects.filter(periodo=periodo).select_related("persona").order_by("persona__apellido_nombre")
    vistos = set()
    for r in renglones:
        if r.persona_id in vistos:
            continue
        vistos.add(r.persona_id)
        cuil = (r.persona.cuil or "").replace("-", "")
        fila = FilaPropuesta(persona=r.persona, cuil=cuil, actual=getattr(r, g["campo"]),
                             actual_del_mes=r.haberes_pagados_en_el_mes)
        if cuil and cuil in importes:
            fila.nuevo = importes[cuil]
            fila.detalle = " | ".join(d for d in detalle[cuil] if d)
            if grupo == "haberes":
                fila.nuevo_del_mes = del_mes[cuil]
        prop.filas.append(fila)
    cuiles_nomina = {f.cuil for f in prop.filas}
    prop.sin_renglon = [(c, nombres.get(c, ""), v) for c, v in sorted(importes.items()) if c not in cuiles_nomina]
    return prop


@transaction.atomic
def aplicar(periodo, grupo, usuario):
    """Graba la propuesta en todos los renglones de cada persona (las que trabajan en dos servicios llevan
    el importe completo en cada renglón, con su %). Devuelve la cantidad de personas actualizadas."""
    prop = propuesta(periodo, grupo)
    campo = GRUPOS[grupo]["campo"]
    nombres_docs = ", ".join(d.nombre_archivo for d in prop.documentos)
    hoy = timezone.localdate().strftime("%d/%m/%Y")
    cambiadas = 0
    for fila in prop.con_cambios:
        for r in LiquidacionNomina.objects.filter(periodo=periodo, persona=fila.persona):
            setattr(r, campo, fila.nuevo)
            if fila.nuevo_del_mes is not None:
                r.haberes_pagados_en_el_mes = min(fila.nuevo_del_mes, fila.nuevo)
            nota = f"{GRUPOS[grupo]['titulo']} según documentos ({nombres_docs}), aplicado el {hoy}: {fila.detalle}"
            r.observaciones = f"{r.observaciones} | {nota}" if r.observaciones else nota
            r.modificado_por = usuario
            r.save()
        cambiadas += 1
    DocumentoNomina.objects.filter(pk__in=[d.pk for d in prop.documentos]).update(aplicado_en=timezone.now())
    return cambiadas, prop


# ---------------------------------------------------------------------------
# Control cruzado: recibos de sueldo contra Libro de Sueldos Digital
# ---------------------------------------------------------------------------

@dataclass
class DiferenciaCruce:
    cuil: str
    nombre: str
    recibos: Decimal = None  # None: la persona no figura en ese documento
    libro: Decimal = None
    recibos_del_mes: Decimal = CERO
    libro_del_mes: Decimal = CERO
    conceptos: list = field(default_factory=list)  # (código, descripción, recibos, libro, diferencia)

    @property
    def diferencia(self):
        return (self.recibos or CERO) - (self.libro or CERO)

    @property
    def diferencia_del_mes(self):
        return self.recibos_del_mes - self.libro_del_mes


@dataclass
class Cruce:
    diferencias: list = field(default_factory=list)
    personas: int = 0
    errores: list = field(default_factory=list)

    @property
    def hay_diferencias(self):
        return bool(self.diferencias)


def _leer_y_sumar(documentos, errores):
    total = lectores.Lectura()
    for doc in documentos:
        try:
            lectura = leer_documento(doc)
        except Exception as error:
            errores.append(f"{doc.nombre_archivo}: {error}")
            continue
        for cuil, valor in lectura.importes.items():
            total.importes[cuil] += valor
            total.del_mes[cuil] += lectura.del_mes.get(cuil, CERO)
            total.nombres.setdefault(cuil, lectura.nombres.get(cuil, ""))
            lectores._sumar_conceptos(total, cuil, [(c, d, v) for c, (d, v) in lectura.conceptos.get(cuil, {}).items()])
    return total


def cruce_recibos_libro(periodo):
    """Compara, persona por persona y concepto por concepto, los recibos del mes con el Libro de Sueldos.
    Devuelve None si en el mes no están subidos los dos."""
    documentos = list(DocumentoNomina.objects.filter(periodo=periodo, tipo__in=[T.RECIBOS, T.LSD]).order_by("creado_en"))
    recibos = [d for d in documentos if d.tipo == T.RECIBOS]
    libro = [d for d in documentos if d.tipo == T.LSD]
    if not recibos or not libro:
        return None
    cruce = Cruce()
    r = _leer_y_sumar(recibos, cruce.errores)
    l = _leer_y_sumar(libro, cruce.errores)
    cuiles = sorted(set(r.importes) | set(l.importes), key=lambda c: r.nombres.get(c) or l.nombres.get(c) or c)
    cruce.personas = len(cuiles)
    for cuil in cuiles:
        d = DiferenciaCruce(
            cuil=cuil, nombre=r.nombres.get(cuil) or l.nombres.get(cuil, ""),
            recibos=r.importes[cuil] if cuil in r.importes else None,
            libro=l.importes[cuil] if cuil in l.importes else None,
            recibos_del_mes=r.del_mes.get(cuil, CERO), libro_del_mes=l.del_mes.get(cuil, CERO),
        )
        falta = d.recibos is None or d.libro is None
        if not falta and abs(d.diferencia) < TOLERANCIA and abs(d.diferencia_del_mes) < TOLERANCIA:
            continue
        cr, cl = r.conceptos.get(cuil, {}), l.conceptos.get(cuil, {})
        for codigo in sorted(set(cr) | set(cl)):
            vr = cr[codigo][1] if codigo in cr else CERO
            vl = cl[codigo][1] if codigo in cl else CERO
            if abs(vr - vl) >= TOLERANCIA:
                descripcion = (cl.get(codigo) or cr.get(codigo))[0]
                d.conceptos.append((codigo, descripcion, vr, vl, vr - vl))
        cruce.diferencias.append(d)
    return cruce

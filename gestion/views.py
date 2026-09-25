"""Pantallas de reportes y página de inicio."""
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import Http404, HttpResponse
from django.shortcuts import render
from django.utils.text import slugify

from . import graficos
from .calculos import calcular_mes, punto_equilibrio
from .exportar import a_excel, a_pdf, texto_celda
from .models import Periodo
from .reportes import REPORTES, estado_resultados, estado_resultados_comparativo
from .roles import puede_ver_reportes

MENU_REPORTES = [
    ("estado-de-resultados", "Estado de Resultados"),
    ("apertura", "Apertura de Costos y Gastos"),
    ("costos-por-servicio", "Costos por Servicio"),
    ("punto-de-equilibrio", "Punto de Equilibrio"),
    ("rentabilidad", "Rentabilidad por Servicio"),
]
# Cuántos meses se muestran si no se elige un rango.
MESES_POR_DEFECTO = {"estado-de-resultados": 6, "apertura": 6}


def _periodo(clave):
    """'2026-07' → Periodo."""
    try:
        anio, mes = (int(x) for x in clave.split("-"))
    except (AttributeError, ValueError):
        return None
    return Periodo.objects.filter(anio=anio, mes=mes).first()


def _rango(request, sufijo, todos, cantidad_por_defecto):
    desde = _periodo(request.GET.get(f"desde{sufijo}"))
    hasta = _periodo(request.GET.get(f"hasta{sufijo}"))
    if hasta is None:
        hasta = todos[-1]
    if desde is None:
        anteriores = [p for p in todos if (p.anio, p.mes) <= (hasta.anio, hasta.mes)]
        desde = anteriores[-cantidad_por_defecto] if len(anteriores) >= cantidad_por_defecto else anteriores[0]
    if (desde.anio, desde.mes) > (hasta.anio, hasta.mes):
        desde, hasta = hasta, desde
    return list(Periodo.objects.entre(desde, hasta))


def _exigir_reportes(request):
    if not puede_ver_reportes(request.user):
        raise PermissionDenied("No tenés permiso para ver los reportes.")


@login_required
def inicio(request):
    contexto = {"menu_reportes": MENU_REPORTES, "ve_reportes": puede_ver_reportes(request.user)}
    periodos = list(Periodo.objects.order_by("anio", "mes"))
    if contexto["ve_reportes"] and periodos:
        ultimo = calcular_mes(periodos[-1])
        general, _ = punto_equilibrio(ultimo.cxs)
        contexto.update({
            "ultimo": ultimo,
            "pe": general,
            "margen_neto": (ultimo.er.resultado_neto / ultimo.er.total_ventas) if ultimo.er.total_ventas else None,
        })
        recientes = periodos[-12:]
        if len(recientes) > 1:
            reporte = estado_resultados(recientes)
            contexto["grafico"] = graficos.barras_por_mes(
                reporte.grafico["meses"], reporte.grafico["series"], "Ventas y resultado neto por mes",
            )
    return render(request, "gestion/inicio.html", contexto)


@login_required
def reporte(request, nombre):
    _exigir_reportes(request)
    if nombre not in REPORTES:
        raise Http404
    todos = list(Periodo.objects.order_by("anio", "mes"))
    contexto = {"menu_reportes": MENU_REPORTES, "nombre": nombre, "ve_reportes": True, "periodos": todos}
    if not todos:
        return render(request, "gestion/reporte.html", {**contexto, "sin_datos": True})

    periodos = _rango(request, "", todos, MESES_POR_DEFECTO.get(nombre, 1))
    comparar = nombre == "estado-de-resultados" and request.GET.get("comparar") == "1"
    if comparar:
        periodos_b = _rango(request, "_b", todos, 1)
        resultado = estado_resultados_comparativo(periodos, periodos_b)
        contexto.update(desde_b=periodos_b[0].clave, hasta_b=periodos_b[-1].clave)
    else:
        resultado = REPORTES[nombre](periodos)

    formato = request.GET.get("formato")
    if formato in ("xlsx", "pdf"):
        archivo = slugify(f"{resultado.titulo} {resultado.subtitulo}")
        if formato == "xlsx":
            respuesta = HttpResponse(
                a_excel(resultado),
                content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        else:
            respuesta = HttpResponse(a_pdf(resultado), content_type="application/pdf")
        respuesta["Content-Disposition"] = f'attachment; filename="{archivo}.{formato}"'
        return respuesta

    grafico = None
    if resultado.grafico and resultado.grafico["tipo"] == "barras_meses":
        grafico = graficos.barras_por_mes(resultado.grafico["meses"], resultado.grafico["series"], "Ventas y resultado neto por mes")
    elif resultado.grafico and resultado.grafico["tipo"] == "barras_servicios":
        grafico = graficos.barras_horizontales_porcentaje(resultado.grafico["servicios"], "Rentabilidad neta (%) por servicio")

    tablas = [
        {
            "tabla": t,
            "filas": [
                {"fila": f, "celdas": [
                    {"texto": texto_celda(t, f, i, v), "negativo": _es_negativo(v)} for i, v in enumerate(f.valores)
                ]}
                for f in t.filas
            ],
        }
        for t in resultado.tablas
    ]
    contexto.update(
        reporte=resultado,
        tablas=tablas,
        grafico=grafico,
        desde=periodos[0].clave,
        hasta=periodos[-1].clave,
        comparar=comparar,
        consulta=request.GET.urlencode(),
    )
    return render(request, "gestion/reporte.html", contexto)


def _es_negativo(valor):
    try:
        return valor is not None and not isinstance(valor, str) and valor < 0
    except TypeError:
        return False

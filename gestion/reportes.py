"""Armado de los 5 reportes como tablas genéricas.

Cada reporte se arma una sola vez como una lista de `Tabla`; la misma
estructura se muestra en pantalla (HTML), se exporta a Excel y a PDF.
"""
from dataclasses import dataclass, field
from decimal import Decimal

from .calculos import (
    CERO,
    FILAS_COSTO_VARIABLE,
    RUBROS_GASTO_BANCARIO,
    RUBROS_GASTO_OPERATIVO,
    calcular_periodos,
    dividir,
    punto_equilibrio,
    ranking,
    sumar_costos_por_servicio,
)
from .catalogos import SERVICIOS, CategoriaCompra, ModoAsignacion, RubroGasto
from .models import GastoManual

MONEDA, PORCENTAJE, TEXTO, ENTERO, DOTACION = "moneda", "porcentaje", "texto", "entero", "dotacion"


@dataclass
class Fila:
    etiqueta: str
    valores: list = field(default_factory=list)
    estilo: str = ""  # "", "seccion", "subtotal", "total", "detalle", "nota"
    formato: str = MONEDA


@dataclass
class Tabla:
    titulo: str
    columnas: list
    filas: list
    primera_columna: str = "Concepto"
    nota: str = ""
    # Formato por columna (opcional). Se aplica a las filas con formato por defecto (moneda).
    formatos: list = None

    def formato(self, fila, indice):
        if self.formatos and fila.formato == MONEDA:
            return self.formatos[indice]
        return fila.formato


@dataclass
class Reporte:
    titulo: str
    subtitulo: str
    tablas: list
    advertencias: list = field(default_factory=list)
    grafico: dict = None  # datos para el gráfico en pantalla (opcional)
    varios_meses: bool = True


def _nombre_rango(periodos):
    if len(periodos) == 1:
        return str(periodos[0])
    return f"{periodos[0]} a {periodos[-1]}"


def _seccion(etiqueta, n):
    return Fila(etiqueta, [None] * n, "seccion")


def _con_acumulado(valores):
    return list(valores) + [sum(valores, CERO)]


# ---------------------------------------------------------------------------
# 1. Estado de Resultados
# ---------------------------------------------------------------------------


def _filas_estado_resultados(ers, acumular=True):
    """Filas del Estado de Resultados para una lista de EstadoResultados (una columna por cada uno)."""
    cols = len(ers) + (1 if acumular else 0)

    def fila(etiqueta, obtener, estilo=""):
        valores = [obtener(er) for er in ers]
        return Fila(etiqueta, _con_acumulado(valores) if acumular else valores, estilo)

    filas = [_seccion("VENTAS POR SERVICIO", cols)]
    filas += [fila(s.label, lambda er, s=s: er.ventas[s]) for s in SERVICIOS]
    filas.append(fila("Total Ventas", lambda er: er.total_ventas, "subtotal"))
    filas.append(_seccion("COSTO DE SERVICIOS PRESTADOS", cols))
    filas += [
        fila("Mano de Obra Directa", lambda er: er.mano_obra_directa),
        fila("Materiales e Insumos", lambda er: er.materiales),
        fila("Combustible", lambda er: er.combustible),
        fila("Mantenimiento de Equipos", lambda er: er.mantenimiento),
        fila("Otros Costos Directos", lambda er: er.otros_costos_directos),
        fila("Total Costo de Servicios Prestados", lambda er: er.total_costo_servicios, "subtotal"),
        fila("UTILIDAD BRUTA", lambda er: er.utilidad_bruta, "total"),
        _seccion("GASTOS OPERATIVOS", cols),
        fila("Sueldos y Cargas Sociales (Administración)", lambda er: er.sueldos_administracion),
    ]
    filas += [fila(r.label, lambda er, r=r: er.gastos_operativos[r]) for r in RUBROS_GASTO_OPERATIVO]
    filas.append(fila("Total Gastos Operativos", lambda er: er.total_gastos_operativos, "subtotal"))
    filas.append(_seccion("GASTOS BANCARIOS Y FINANCIEROS", cols))
    filas += [fila(RubroGasto(r).label, lambda er, r=r: er.gastos_bancarios[r]) for r in RUBROS_GASTO_BANCARIO]
    filas += [
        fila("Total Gastos Bancarios", lambda er: er.total_gastos_bancarios, "subtotal"),
        fila("RESULTADO OPERATIVO", lambda er: er.resultado_operativo, "total"),
        _seccion("OTROS INGRESOS Y EGRESOS", cols),
        fila("Otros Ingresos", lambda er: er.otros_ingresos),
        fila("Otros Egresos (no operativos)", lambda er: er.otros_egresos),
        fila("RESULTADO ANTES DE IMPUESTOS", lambda er: er.resultado_antes_impuestos, "subtotal"),
        fila("Impuesto a las Ganancias (estimado)", lambda er: er.impuesto_ganancias),
        fila("RESULTADO NETO DEL PERÍODO", lambda er: er.resultado_neto, "total"),
    ]
    # La rentabilidad es un %: se recalcula por columna (no se suma).
    ventas = next(f for f in filas if f.etiqueta == "Total Ventas").valores
    netos = filas[-1].valores
    filas.append(Fila(
        "Rentabilidad neta sobre ventas", [dividir(n, v) for n, v in zip(netos, ventas)], "detalle", PORCENTAJE,
    ))
    return filas


def estado_resultados(periodos):
    meses = calcular_periodos(periodos)
    ers = [m.er for m in meses]
    columnas = [p.nombre_corto for p in periodos] + ["Acumulado"]
    filas = _filas_estado_resultados(ers)
    filas.append(_seccion("MEMO: SALDO DE PROVEEDORES (no forma parte del resultado)", len(columnas)))
    saldos = [p.saldo_proveedores for p in periodos]
    filas.append(Fila("Saldo de Proveedores al cierre del mes", saldos + [None]))
    variaciones = [None] + [
        (b - a) if a is not None and b is not None else None for a, b in zip(saldos, saldos[1:])
    ]
    filas.append(Fila("Variación respecto al mes anterior", variaciones + [None], "detalle"))
    return Reporte(
        titulo="Estado de Resultados",
        subtitulo=_nombre_rango(periodos),
        tablas=[Tabla("Estado de Resultados", columnas, filas)],
        grafico={
            "tipo": "barras_meses",
            "meses": [p.nombre_corto for p in periodos],
            "series": [
                ("Ventas", [er.total_ventas for er in ers]),
                ("Resultado neto", [er.resultado_neto for er in ers]),
            ],
        } if len(periodos) > 1 else None,
    )


def estado_resultados_comparativo(periodos_a, periodos_b):
    """Compara dos períodos (cada uno puede ser uno o varios meses) con variación $ y %."""
    er_a = _sumar_er([m.er for m in calcular_periodos(periodos_a)])
    er_b = _sumar_er([m.er for m in calcular_periodos(periodos_b)])
    nombre_a, nombre_b = _nombre_rango(periodos_a), _nombre_rango(periodos_b)
    filas = []
    for f in _filas_estado_resultados([er_a, er_b], acumular=False):
        if f.estilo == "seccion":
            filas.append(Fila(f.etiqueta, [None] * 4, "seccion"))
            continue
        a, b = f.valores
        if f.formato == PORCENTAJE:
            filas.append(Fila(f.etiqueta, [a, b, None, None], f.estilo, PORCENTAJE))
            continue
        variacion = b - a
        filas.append(Fila(f.etiqueta, [a, b, variacion, dividir(variacion, abs(a)) if a else None], f.estilo))
    return Reporte(
        titulo="Estado de Resultados — Comparativo",
        subtitulo=f"{nombre_b} vs. {nombre_a}",
        tablas=[Tabla(
            "Comparativo", [nombre_a, nombre_b, "Variación $", "Variación %"], filas,
            formatos=[MONEDA, MONEDA, MONEDA, PORCENTAJE],
        )],
        varios_meses=False,
    )


def _sumar_er(ers):
    """Suma varios Estados de Resultados (para comparar períodos de varios meses)."""
    if len(ers) == 1:
        return ers[0]
    primero = ers[0]
    sumado = {}
    for nombre, valor in vars(primero).items():
        if isinstance(valor, dict):
            sumado[nombre] = {k: sum((er.__dict__[nombre][k] for er in ers), CERO) for k in valor}
        else:
            sumado[nombre] = sum((er.__dict__[nombre] for er in ers), CERO)
    return type(primero)(**sumado)


# ---------------------------------------------------------------------------
# 2. Apertura de Costos y Gastos
# ---------------------------------------------------------------------------


def apertura(periodos):
    meses = calcular_periodos(periodos)
    n = len(periodos)
    columnas = [p.nombre_corto for p in periodos] + ["Acumulado"]
    items = GastoManual.objects.filter(periodo__in=periodos).values_list("periodo_id", "rubro", "concepto", "monto")
    # {rubro: {concepto: {periodo_id: monto}}}
    detalle = {}
    for periodo_id, rubro, concepto, monto in items:
        por_mes = detalle.setdefault(rubro, {}).setdefault(concepto, {})
        por_mes[periodo_id] = por_mes.get(periodo_id, CERO) + monto

    def automatica(etiqueta, obtener):
        return Fila(etiqueta, _con_acumulado([obtener(m) for m in meses]), "detalle")

    def subtotal(etiqueta, filas_rubro):
        valores = [sum((f.valores[i] for f in filas_rubro), CERO) for i in range(n + 1)]
        return Fila(f"Subtotal — {etiqueta}", valores, "subtotal")

    def manuales(rubro):
        return [
            Fila(concepto, _con_acumulado([por_mes.get(p.pk, CERO) for p in periodos]), "detalle")
            for concepto, por_mes in sorted(detalle.get(rubro, {}).items())
        ]

    filas = [_seccion("COSTO DE SERVICIOS PRESTADOS — DETALLE", n + 1)]
    automaticas = [
        ("Mano de Obra Directa", 'Automático — "Personal y Nómina" (¿Mano de Obra Directa? = Sí)', lambda m: m.er.mano_obra_directa),
        ("Materiales e Insumos", 'Automático — "Registro de Compras"', lambda m: m.er.materiales),
        ("Combustible", 'Automático — "Registro de Compras"', lambda m: m.er.combustible),
        ("Mantenimiento de Equipos", 'Automático — "Registro de Compras"', lambda m: m.er.mantenimiento),
        ("Otros Costos Directos", 'Automático — "Registro de Compras"', lambda m: m.er.otros_costos_directos),
    ]
    for titulo, etiqueta, obtener in automaticas:
        filas.append(Fila(titulo, [None] * (n + 1), "rubro"))
        renglon = automatica(etiqueta, obtener)
        filas += [renglon, subtotal(titulo, [renglon])]

    filas.append(_seccion("GASTOS OPERATIVOS — DETALLE", n + 1))
    titulo = "Sueldos y Cargas Sociales (Administración)"
    filas.append(Fila(titulo, [None] * (n + 1), "rubro"))
    renglon = automatica('Automático — "Personal y Nómina" (¿Mano de Obra Directa? = No)', lambda m: m.er.sueldos_administracion)
    filas += [renglon, subtotal(titulo, [renglon])]
    for rubro in RUBROS_GASTO_OPERATIVO:
        filas.append(Fila(rubro.label, [None] * (n + 1), "rubro"))
        renglones = []
        if rubro == RubroGasto.OTROS_GASTOS_OPERATIVOS:
            renglones.append(automatica(
                'Automático — "Registro de Compras" (Categoría = Otros Egresos)', lambda m: m.er.compras_otros_egresos,
            ))
        renglones += manuales(rubro)
        if not renglones:
            renglones = [Fila("(sin ítems cargados)", _con_acumulado([CERO] * n), "detalle")]
        filas += renglones + [subtotal(rubro.label, renglones)]

    otros_rubros = [
        ("GASTOS BANCARIOS Y FINANCIEROS — DETALLE", RUBROS_GASTO_BANCARIO),
        ("OTROS INGRESOS Y EGRESOS — DETALLE", [
            RubroGasto.OTROS_INGRESOS, RubroGasto.OTROS_EGRESOS_NO_OPERATIVOS, RubroGasto.IMPUESTO_GANANCIAS,
        ]),
    ]
    for titulo_seccion, rubros in otros_rubros:
        filas.append(_seccion(titulo_seccion, n + 1))
        for rubro in rubros:
            rubro = RubroGasto(rubro)
            filas.append(Fila(rubro.label, [None] * (n + 1), "rubro"))
            renglones = manuales(rubro) or [Fila("(sin ítems cargados)", _con_acumulado([CERO] * n), "detalle")]
            filas += renglones + [subtotal(rubro.label, renglones)]

    return Reporte(
        titulo="Apertura de Costos y Gastos",
        subtitulo=_nombre_rango(periodos),
        tablas=[Tabla(
            "Apertura de Costos y Gastos", columnas, filas,
            nota='Los renglones "Automático" salen solos de los registros de carga. El resto se carga en '
                 '"Apertura de gastos (carga manual)", ítem por ítem.',
        )],
    )


# ---------------------------------------------------------------------------
# 3. Costos por Servicio
# ---------------------------------------------------------------------------


def _cxs(periodos):
    meses = calcular_periodos(periodos)
    return meses, sumar_costos_por_servicio([m.cxs for m in meses])


def costos_por_servicio(periodos):
    meses, cxs = _cxs(periodos)
    columnas = [s.label for s in SERVICIOS] + ["TOTAL"]

    def fila(etiqueta, valores, total, estilo="", formato=MONEDA):
        return Fila(etiqueta, [valores[s] for s in SERVICIOS] + [total], estilo, formato)

    vacios = [None] * 9
    filas = [
        _seccion("VENTAS DEL PERÍODO", 10),
        fila("Ventas Netas", cxs.ventas, cxs.total_ventas, "subtotal"),
        Fila(
            "Pool Operativo del período (a prorratear entre los 7 servicios del pool por ventas)",
            vacios + [cxs.pool_operativo], "detalle",
        ),
        _seccion("COSTOS VARIABLES / DIRECTOS", 10),
    ]
    for clave, etiqueta in FILAS_COSTO_VARIABLE:
        filas.append(fila(etiqueta, cxs.costos_variables[clave], cxs.total_fila(clave)))
    filas.append(fila(
        "Personal afectado (personas equivalentes" + (", promedio mensual)" if len(periodos) > 1 else ")"),
        cxs.dotacion, sum(cxs.dotacion.values(), CERO), "detalle", DOTACION,
    ))
    filas.append(fila(
        "% de personal afectado (reparto de EPP)", cxs.porcentaje_dotacion,
        sum(cxs.porcentaje_dotacion.values(), CERO), "detalle", PORCENTAJE,
    ))
    filas += [
        fila("Total Costos Variables", cxs.total_costos_variables, cxs.total_cv, "subtotal"),
        fila("MARGEN DE CONTRIBUCIÓN ($)", cxs.margen_contribucion, cxs.total_mc, "total"),
        fila("MARGEN DE CONTRIBUCIÓN (%)", {s: cxs.mc_porcentaje(s) for s in SERVICIOS}, cxs.mc_porcentaje(), "", PORCENTAJE),
        _seccion("COSTOS FIJOS / ESTRUCTURA", 10),
        Fila("Total Gastos Operativos", vacios + [cxs.total_gastos_operativos], "detalle"),
        Fila("Total Gastos Bancarios", vacios + [cxs.total_gastos_bancarios], "detalle"),
        Fila("Total Costos Fijos del Período", vacios + [cxs.costos_fijos], "subtotal"),
        fila(
            f"% de Asignación de Costos Fijos ({_modo(cxs.modo_asignacion)})",
            cxs.porcentaje_asignacion, sum(cxs.porcentaje_asignacion.values(), CERO), "", PORCENTAJE,
        ),
        fila("Costos Fijos Asignados ($)", cxs.costos_fijos_asignados, sum(cxs.costos_fijos_asignados.values(), CERO)),
        fila("RESULTADO NETO POR SERVICIO", cxs.resultado_neto, cxs.total_resultado, "total"),
        fila("RENTABILIDAD NETA (%)", {s: cxs.rentabilidad(s) for s in SERVICIOS}, cxs.rentabilidad(), "", PORCENTAJE),
    ]
    return Reporte(
        titulo="Costos por Servicio",
        subtitulo=_nombre_rango(periodos) + (" (acumulado)" if len(periodos) > 1 else ""),
        tablas=[Tabla(
            "Costos por Servicio", columnas, filas,
            nota="Mano de Obra Directa: Soporte PAE y Cercos suman su cuadrilla fija; el resto suma el personal "
                 "asignado directo a cada servicio más su parte del Pool Operativo según ventas. Las compras "
                 "GENERAL y los costos fijos se reparten con el % de Asignación; las compras de EPP, según el "
                 "personal afectado a cada servicio. La suma del Resultado Neto por "
                 "Servicio es igual al Resultado Operativo del Estado de Resultados.",
        )],
        advertencias=cxs.advertencias,
        varios_meses=False,
    )


def _modo(modo):
    if modo == "MIXTO":
        return "automático y manual según el mes"
    return ModoAsignacion(modo).label


# ---------------------------------------------------------------------------
# 4. Punto de Equilibrio
# ---------------------------------------------------------------------------


def punto_de_equilibrio(periodos):
    meses, cxs = _cxs(periodos)
    general, por_servicio = punto_equilibrio(cxs)
    tabla_general = Tabla(
        "Punto de Equilibrio general",
        ["Valor"],
        [
            Fila("Ventas Totales del Período", [general.ventas]),
            Fila("Costos Variables Totales", [general.costos_variables]),
            Fila("Margen de Contribución Total ($)", [general.margen_contribucion]),
            Fila("Margen de Contribución (%) Ponderado", [general.mc_porcentaje], formato=PORCENTAJE),
            Fila("Costos Fijos Totales del Período", [general.costos_fijos]),
            Fila("PUNTO DE EQUILIBRIO EN PESOS ($)", [general.punto_equilibrio], "total"),
            Fila("Ventas Actuales del Período", [general.ventas]),
            Fila("Diferencia vs. Punto de Equilibrio ($)", [general.diferencia], "subtotal"),
            Fila("Margen de Seguridad (%)", [general.margen_seguridad], formato=PORCENTAJE),
            Fila("Estado", [general.estado], "destacado", TEXTO),
        ],
        nota="Punto de Equilibrio = Costos Fijos ÷ Margen de Contribución %. "
             "Costos Fijos = Total Gastos Operativos + Total Gastos Bancarios.",
    )
    filas = []
    for s in SERVICIOS:
        pe = por_servicio[s]
        filas.append(Fila(
            s.label,
            [pe.ventas, pe.mc_porcentaje, pe.costos_fijos, pe.punto_equilibrio, pe.diferencia,
             pe.estado if pe.ventas or pe.costos_fijos else "Sin actividad"],
        ))
    filas.append(Fila(
        "TOTAL",
        [general.ventas, general.mc_porcentaje, general.costos_fijos, general.punto_equilibrio,
         sum((por_servicio[s].diferencia for s in SERVICIOS), CERO), general.estado],
        "total",
    ))
    tabla_servicios = Tabla(
        "Punto de Equilibrio por línea de servicio",
        ["Ventas Actuales", "Margen de Contribución %", "Costos Fijos Asignados", "Punto de Equilibrio ($)",
         "Margen de Seguridad ($)", "Estado"],
        filas,
        primera_columna="Servicio",
        formatos=[MONEDA, PORCENTAJE, MONEDA, MONEDA, MONEDA, TEXTO],
    )
    return Reporte(
        titulo="Punto de Equilibrio",
        subtitulo=_nombre_rango(periodos) + (" (acumulado)" if len(periodos) > 1 else ""),
        tablas=[tabla_general, tabla_servicios],
        advertencias=cxs.advertencias,
        varios_meses=False,
    )


# ---------------------------------------------------------------------------
# 5. Rentabilidad por Servicio
# ---------------------------------------------------------------------------


def rentabilidad(periodos):
    meses, cxs = _cxs(periodos)
    rentabilidades = {s: cxs.rentabilidad(s) for s in SERVICIOS}
    puestos = ranking(rentabilidades)
    orden = sorted(SERVICIOS, key=lambda s: (puestos[s], s.label))
    filas = [
        Fila(
            s.label,
            [puestos[s], cxs.ventas[s], cxs.total_costos_variables[s], cxs.margen_contribucion[s],
             cxs.mc_porcentaje(s), cxs.costos_fijos_asignados[s], cxs.resultado_neto[s], rentabilidades[s]],
        )
        for s in orden
    ]
    filas.append(Fila(
        "TOTAL / PROMEDIO",
        [None, cxs.total_ventas, cxs.total_cv, cxs.total_mc, cxs.mc_porcentaje(),
         sum(cxs.costos_fijos_asignados.values(), CERO), cxs.total_resultado, cxs.rentabilidad()],
        "total",
    ))
    tablas = [Tabla(
        "Ranking de rentabilidad",
        ["Ranking", "Ventas", "Costos Variables", "Margen de Contribución ($)", "Margen de Contribución (%)",
         "Costos Fijos Asignados", "Resultado Neto", "Rentabilidad Neta (%)"],
        filas,
        primera_columna="Servicio",
        formatos=[ENTERO, MONEDA, MONEDA, MONEDA, PORCENTAJE, MONEDA, MONEDA, PORCENTAJE],
    )]
    if len(meses) > 1:
        columnas = [m.periodo.nombre_corto for m in meses] + ["Acumulado"]
        tablas.append(Tabla(
            "Evolución de la Rentabilidad Neta (%)",
            columnas,
            [
                Fila(s.label, [m.cxs.rentabilidad(s) for m in meses] + [cxs.rentabilidad(s)], formato=PORCENTAJE)
                for s in SERVICIOS
            ] + [Fila("TOTAL", [m.cxs.rentabilidad() for m in meses] + [cxs.rentabilidad()], "total", PORCENTAJE)],
            primera_columna="Servicio",
        ))
        tablas.append(Tabla(
            "Evolución del Resultado Neto por Servicio ($)",
            columnas,
            [
                Fila(s.label, _con_acumulado([m.cxs.resultado_neto[s] for m in meses]))
                for s in SERVICIOS
            ] + [Fila("TOTAL", _con_acumulado([m.cxs.total_resultado for m in meses]), "total")],
            primera_columna="Servicio",
        ))
    return Reporte(
        titulo="Rentabilidad por Servicio",
        subtitulo=_nombre_rango(periodos) + (" (acumulado)" if len(periodos) > 1 else ""),
        tablas=tablas,
        advertencias=cxs.advertencias,
        grafico={
            "tipo": "barras_servicios",
            "servicios": [(s.label, rentabilidades[s]) for s in orden],
        },
    )


REPORTES = {
    "estado-de-resultados": estado_resultados,
    "apertura": apertura,
    "costos-por-servicio": costos_por_servicio,
    "punto-de-equilibrio": punto_de_equilibrio,
    "rentabilidad": rentabilidad,
}

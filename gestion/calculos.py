"""Motor de cálculo: reproduce la lógica del Excel a partir de los datos cargados.

Flujo (el mismo del Excel):

    Personal y Nómina + Registro de Compras + Registro de Ventas + Gastos manuales
        → DatosMes (sumas del mes, una sola lectura a la base)
        → Estado de Resultados del mes
        → Costos por Servicio del mes (reglas 1 a 5)
        → Punto de Equilibrio / Rentabilidad por Servicio

Todo se calcula con Decimal (sin errores de redondeo de punto flotante); se
redondea recién al mostrar. Las funciones que calculan no tocan la base de
datos: reciben un `DatosMes`, así se pueden probar de forma aislada.
"""
from collections import defaultdict
from dataclasses import dataclass, field
from decimal import Decimal

from .catalogos import (
    CATEGORIAS_COSTO_DIRECTO,
    GRUPO_DE_RUBRO,
    SERVICIOS,
    SERVICIOS_POOL,
    AsignacionPersonal,
    CategoriaCompra,
    GrupoRubro,
    ModoAsignacion,
    RubroGasto,
    ServicioCompra,
)

CERO = Decimal("0")
CIEN = Decimal("100")

# Rubros de Gastos Operativos en el orden del Estado de Resultados.
RUBROS_GASTO_OPERATIVO = [
    RubroGasto.ALQUILERES,
    RubroGasto.SERVICIOS,
    RubroGasto.SEGUROS,
    RubroGasto.IMPUESTOS_TASAS,
    RubroGasto.OTROS_GASTOS_OPERATIVOS,
    RubroGasto.LEASING,
    RubroGasto.PLANES_PAGO,
]
RUBROS_GASTO_BANCARIO = [r for r, g in GRUPO_DE_RUBRO.items() if g == GrupoRubro.GASTO_BANCARIO]


def dividir(a, b):
    """División que devuelve 0 si el divisor es 0 (como el SI.ERROR del Excel)."""
    return a / b if b else CERO


def _por_servicio(valor=CERO):
    return {s: valor for s in SERVICIOS}


# ---------------------------------------------------------------------------
# Datos de un mes
# ---------------------------------------------------------------------------


@dataclass
class DatosMes:
    """Sumas de un mes, tal como salen de las tablas de carga."""

    periodo: object = None
    ventas: dict = field(default_factory=_por_servicio)
    # Mano de obra directa ($ Asignado al Servicio, ¿MOD? = Sí) por Servicio Asignado (incluye "POOL").
    mano_obra: dict = field(default_factory=lambda: defaultdict(lambda: CERO))
    # Personas equivalentes con ¿MOD? = Sí, por Servicio Asignado (incluye "POOL").
    # Una persona al 50% en un servicio cuenta 0,5.
    dotacion: dict = field(default_factory=lambda: defaultdict(lambda: CERO))
    # Nómina con ¿MOD? = No (estructura de Administración).
    sueldos_administracion: Decimal = CERO
    # Compras por (categoría, servicio asignado).
    compras: dict = field(default_factory=lambda: defaultdict(lambda: CERO))
    # Gastos manuales por rubro.
    gastos: dict = field(default_factory=lambda: defaultdict(lambda: CERO))
    modo_asignacion: str = ModoAsignacion.AUTOMATICO
    # % manual por servicio, en escala 0-100.
    asignacion_manual: dict = field(default_factory=_por_servicio)

    @classmethod
    def desde_base(cls, periodo):
        from .models import Compra, GastoManual, LiquidacionNomina, Venta

        datos = cls(periodo=periodo, modo_asignacion=periodo.modo_asignacion)

        # Las sumas se hacen en Python con Decimal (y no con SUM en la base) para que
        # el resultado sea exacto al centavo también en SQLite, que suma en punto flotante.
        for servicio, monto in Venta.objects.filter(periodo=periodo).values_list("servicio", "monto"):
            datos.ventas[servicio] += monto

        for renglon in LiquidacionNomina.objects.filter(periodo=periodo):
            if renglon.mano_obra_directa:
                datos.mano_obra[renglon.asignacion] += renglon.asignado_servicio
                datos.dotacion[renglon.asignacion] += renglon.porcentaje_afectacion / CIEN
            else:
                datos.sueldos_administracion += renglon.asignado_servicio

        compras = Compra.objects.filter(periodo=periodo).values_list("categoria", "servicio_asignado", "monto")
        for categoria, servicio, monto in compras:
            datos.compras[(categoria, servicio)] += monto

        for rubro, monto in GastoManual.objects.filter(periodo=periodo).values_list("rubro", "monto"):
            datos.gastos[rubro] += monto

        for a in periodo.asignaciones_manuales.all():
            datos.asignacion_manual[a.servicio] = a.porcentaje
        return datos

    def compras_categoria(self, categoria):
        return sum((v for (c, _), v in self.compras.items() if c == categoria), CERO)


# ---------------------------------------------------------------------------
# Estado de Resultados
# ---------------------------------------------------------------------------


@dataclass
class EstadoResultados:
    ventas: dict
    total_ventas: Decimal
    mano_obra_directa: Decimal
    materiales: Decimal
    combustible: Decimal
    mantenimiento: Decimal
    otros_costos_directos: Decimal
    total_costo_servicios: Decimal
    utilidad_bruta: Decimal
    sueldos_administracion: Decimal
    # Rubros de gastos operativos (Otros Gastos Operativos incluye las compras "Otros Egresos").
    gastos_operativos: dict
    total_gastos_operativos: Decimal
    gastos_bancarios: dict
    total_gastos_bancarios: Decimal
    resultado_operativo: Decimal
    otros_ingresos: Decimal
    otros_egresos: Decimal
    resultado_antes_impuestos: Decimal
    impuesto_ganancias: Decimal
    resultado_neto: Decimal
    # Parte de "Otros Gastos Operativos" que viene de Registro de Compras.
    compras_otros_egresos: Decimal = CERO


def estado_resultados(datos: DatosMes) -> EstadoResultados:
    total_ventas = sum(datos.ventas.values(), CERO)
    mano_obra_directa = sum(datos.mano_obra.values(), CERO)
    materiales = datos.compras_categoria(CategoriaCompra.MATERIALES)
    combustible = datos.compras_categoria(CategoriaCompra.COMBUSTIBLE)
    mantenimiento = datos.compras_categoria(CategoriaCompra.MANTENIMIENTO_EQUIPOS)
    otros_directos = datos.compras_categoria(CategoriaCompra.OTROS_COSTOS_DIRECTOS)
    total_csp = mano_obra_directa + materiales + combustible + mantenimiento + otros_directos
    utilidad_bruta = total_ventas - total_csp

    # Regla 2: las compras "Otros Egresos" van directo a Otros Gastos Operativos.
    compras_otros_egresos = datos.compras_categoria(CategoriaCompra.OTROS_EGRESOS)
    gastos_operativos = {r: datos.gastos[r] for r in RUBROS_GASTO_OPERATIVO}
    gastos_operativos[RubroGasto.OTROS_GASTOS_OPERATIVOS] += compras_otros_egresos
    total_go = datos.sueldos_administracion + sum(gastos_operativos.values(), CERO)

    gastos_bancarios = {r: datos.gastos[r] for r in RUBROS_GASTO_BANCARIO}
    total_gb = sum(gastos_bancarios.values(), CERO)

    resultado_operativo = utilidad_bruta - total_go - total_gb
    otros_ingresos = datos.gastos[RubroGasto.OTROS_INGRESOS]
    otros_egresos = datos.gastos[RubroGasto.OTROS_EGRESOS_NO_OPERATIVOS]
    rai = resultado_operativo + otros_ingresos - otros_egresos
    ganancias = datos.gastos[RubroGasto.IMPUESTO_GANANCIAS]

    return EstadoResultados(
        ventas=dict(datos.ventas),
        total_ventas=total_ventas,
        mano_obra_directa=mano_obra_directa,
        materiales=materiales,
        combustible=combustible,
        mantenimiento=mantenimiento,
        otros_costos_directos=otros_directos,
        total_costo_servicios=total_csp,
        utilidad_bruta=utilidad_bruta,
        sueldos_administracion=datos.sueldos_administracion,
        gastos_operativos=gastos_operativos,
        total_gastos_operativos=total_go,
        gastos_bancarios=gastos_bancarios,
        total_gastos_bancarios=total_gb,
        resultado_operativo=resultado_operativo,
        otros_ingresos=otros_ingresos,
        otros_egresos=otros_egresos,
        resultado_antes_impuestos=rai,
        impuesto_ganancias=ganancias,
        resultado_neto=rai - ganancias,
        compras_otros_egresos=compras_otros_egresos,
    )


# ---------------------------------------------------------------------------
# Costos por Servicio
# ---------------------------------------------------------------------------

# Filas de costo variable en el orden de "Costos por Servicio" (filas 10 a 14).
FILAS_COSTO_VARIABLE = [
    ("mano_obra", "Mano de Obra Directa"),
    (CategoriaCompra.MATERIALES, "Materiales e Insumos"),
    (CategoriaCompra.COMBUSTIBLE, "Combustible"),
    (CategoriaCompra.MANTENIMIENTO_EQUIPOS, "Mantenimiento de Equipos Específicos"),
    (CategoriaCompra.OTROS_COSTOS_DIRECTOS, "Otros Costos Variables"),
]


@dataclass
class CostosPorServicio:
    ventas: dict
    pool_operativo: Decimal
    # costos_variables[fila][servicio]; fila = "mano_obra" o una categoría de compra.
    costos_variables: dict
    total_costos_variables: dict
    margen_contribucion: dict
    total_gastos_operativos: Decimal
    total_gastos_bancarios: Decimal
    costos_fijos: Decimal
    modo_asignacion: str
    # % efectivo de asignación, en escala 0-1.
    porcentaje_asignacion: dict
    costos_fijos_asignados: dict
    resultado_neto: dict
    advertencias: list = field(default_factory=list)
    # Personal afectado (personas equivalentes) y su proporción, para las compras
    # "a prorratear por personal afectado" (EPP).
    dotacion: dict = field(default_factory=lambda: {s: CERO for s in SERVICIOS})
    porcentaje_dotacion: dict = field(default_factory=lambda: {s: CERO for s in SERVICIOS})

    # --- totales y porcentajes derivados -------------------------------------
    @property
    def total_ventas(self):
        return sum(self.ventas.values(), CERO)

    def total_fila(self, fila):
        return sum(self.costos_variables[fila].values(), CERO)

    @property
    def total_cv(self):
        return sum(self.total_costos_variables.values(), CERO)

    @property
    def total_mc(self):
        return sum(self.margen_contribucion.values(), CERO)

    @property
    def total_resultado(self):
        return sum(self.resultado_neto.values(), CERO)

    def mc_porcentaje(self, servicio=None):
        if servicio is None:
            return dividir(self.total_mc, self.total_ventas)
        return dividir(self.margen_contribucion[servicio], self.ventas[servicio])

    def rentabilidad(self, servicio=None):
        if servicio is None:
            return dividir(self.total_resultado, self.total_ventas)
        return dividir(self.resultado_neto[servicio], self.ventas[servicio])


def porcentaje_asignacion(datos: DatosMes):
    """Regla 3: participación en las ventas del mes, o el % manual si el mes está en modo Manual."""
    if datos.modo_asignacion == ModoAsignacion.MANUAL:
        return {s: datos.asignacion_manual[s] / CIEN for s in SERVICIOS}
    total = sum(datos.ventas.values(), CERO)
    return {s: dividir(datos.ventas[s], total) for s in SERVICIOS}


def dotacion_por_servicio(datos: DatosMes):
    """Personal afectado a cada servicio (personas equivalentes, sin Administración).

    Las cuadrillas fijas y las personas asignadas directo a un servicio cuentan en
    ese servicio; las del Pool Operativo se reparten entre los 7 servicios del pool
    según sus ventas del mes, igual que su costo de mano de obra (regla 4).
    """
    ventas_pool = sum((datos.ventas[s] for s in SERVICIOS_POOL), CERO)
    pool = datos.dotacion[AsignacionPersonal.POOL]
    return {
        s: datos.dotacion[s.value]
        + (dividir(pool * datos.ventas[s], ventas_pool) if s in SERVICIOS_POOL else CERO)
        for s in SERVICIOS
    }


def costos_por_servicio(datos: DatosMes, er: EstadoResultados = None) -> CostosPorServicio:
    er = er or estado_resultados(datos)
    advertencias = []
    pct = porcentaje_asignacion(datos)

    if datos.modo_asignacion == ModoAsignacion.MANUAL:
        suma_manual = sum(datos.asignacion_manual.values(), CERO)
        if suma_manual != CIEN:
            advertencias.append(
                f"El % manual de asignación suma {suma_manual}% en lugar de 100%: "
                "los costos fijos y las compras GENERAL no se reparten completos."
            )

    # Regla 4: mano de obra. Cada servicio suma lo asignado directo a él
    # (cuadrillas fijas de PAE y Cercos, y cualquier persona asignada puntualmente
    # a otro servicio) más, para los 7 servicios del pool, su parte del Pool
    # Operativo en proporción a sus ventas del mes.
    pool = datos.mano_obra[AsignacionPersonal.POOL]
    ventas_pool = sum((datos.ventas[s] for s in SERVICIOS_POOL), CERO)
    mano_obra = {}
    for s in SERVICIOS:
        directo = datos.mano_obra[s.value]
        parte_pool = dividir(pool * datos.ventas[s], ventas_pool) if s in SERVICIOS_POOL else CERO
        mano_obra[s] = directo + parte_pool
    if pool and not ventas_pool:
        advertencias.append(
            "Hay costo de Pool Operativo pero los 7 servicios del pool no tuvieron ventas en el mes: "
            "ese costo no se pudo repartir y no aparece en Costos por Servicio (sí en el Estado de Resultados)."
        )

    # Reglas 1 y 5: compras directas + la parte de las facturas GENERAL según el % de asignación
    # + la parte de las facturas a prorratear por personal afectado (EPP) según la dotación.
    dotacion = dotacion_por_servicio(datos)
    total_dotacion = sum(dotacion.values(), CERO)
    pct_dotacion = {s: dividir(dotacion[s], total_dotacion) for s in SERVICIOS}
    costos_variables = {"mano_obra": mano_obra}
    for categoria in CATEGORIAS_COSTO_DIRECTO:
        general = datos.compras[(categoria, ServicioCompra.GENERAL.value)]
        por_personal = datos.compras[(categoria, ServicioCompra.POR_PERSONAL.value)]
        costos_variables[categoria] = {
            s: datos.compras[(categoria, s.value)] + general * pct[s] + por_personal * pct_dotacion[s]
            for s in SERVICIOS
        }
        if general and not any(pct.values()):
            advertencias.append(
                f"Hay compras GENERAL de {categoria.label} pero no hay ventas en el mes para prorratearlas."
            )
        if por_personal and not total_dotacion:
            advertencias.append(
                f"Hay compras de {categoria.label} a prorratear por personal afectado, pero el mes no tiene "
                "personal de mano de obra directa cargado en Personal y Nómina: no se pudieron repartir."
            )

    total_cv = {s: sum((costos_variables[f][s] for f, _ in FILAS_COSTO_VARIABLE), CERO) for s in SERVICIOS}
    margen = {s: datos.ventas[s] - total_cv[s] for s in SERVICIOS}

    # Costos fijos = Gastos Operativos + Gastos Bancarios del mes (incluye Sueldos de Administración).
    costos_fijos = er.total_gastos_operativos + er.total_gastos_bancarios
    asignados = {s: costos_fijos * pct[s] for s in SERVICIOS}
    if costos_fijos and not any(pct.values()):
        advertencias.append("Hay costos fijos pero no hay ventas en el mes para asignarlos entre servicios.")

    return CostosPorServicio(
        ventas=dict(datos.ventas),
        pool_operativo=pool,
        costos_variables=costos_variables,
        total_costos_variables=total_cv,
        margen_contribucion=margen,
        total_gastos_operativos=er.total_gastos_operativos,
        total_gastos_bancarios=er.total_gastos_bancarios,
        costos_fijos=costos_fijos,
        modo_asignacion=datos.modo_asignacion,
        porcentaje_asignacion=pct,
        costos_fijos_asignados=asignados,
        resultado_neto={s: margen[s] - asignados[s] for s in SERVICIOS},
        advertencias=advertencias,
        dotacion=dotacion,
        porcentaje_dotacion=pct_dotacion,
    )


def sumar_costos_por_servicio(meses):
    """Acumula varios meses: suma los importes de cada mes y recalcula los %."""
    if len(meses) == 1:
        return meses[0]

    def sumar(atributo):
        return {s: sum((getattr(m, atributo)[s] for m in meses), CERO) for s in SERVICIOS}

    costos_fijos = sum((m.costos_fijos for m in meses), CERO)
    asignados = sumar("costos_fijos_asignados")
    modos = {m.modo_asignacion for m in meses}
    return CostosPorServicio(
        ventas=sumar("ventas"),
        pool_operativo=sum((m.pool_operativo for m in meses), CERO),
        costos_variables={
            fila: {s: sum((m.costos_variables[fila][s] for m in meses), CERO) for s in SERVICIOS}
            for fila, _ in FILAS_COSTO_VARIABLE
        },
        total_costos_variables=sumar("total_costos_variables"),
        margen_contribucion=sumar("margen_contribucion"),
        total_gastos_operativos=sum((m.total_gastos_operativos for m in meses), CERO),
        total_gastos_bancarios=sum((m.total_gastos_bancarios for m in meses), CERO),
        costos_fijos=costos_fijos,
        modo_asignacion=modos.pop() if len(modos) == 1 else "MIXTO",
        # En un acumulado, el % efectivo es la proporción de costos fijos que recibió cada servicio.
        porcentaje_asignacion={s: dividir(asignados[s], costos_fijos) for s in SERVICIOS},
        costos_fijos_asignados=asignados,
        resultado_neto=sumar("resultado_neto"),
        advertencias=[a for m in meses for a in m.advertencias],
        # En un acumulado, la dotación es el promedio mensual.
        dotacion={s: v / len(meses) for s, v in sumar("dotacion").items()},
        porcentaje_dotacion={s: dividir(v, sum(sumar("dotacion").values(), CERO)) for s, v in sumar("dotacion").items()},
    )


# ---------------------------------------------------------------------------
# Punto de Equilibrio
# ---------------------------------------------------------------------------


@dataclass
class PuntoEquilibrio:
    ventas: Decimal
    costos_variables: Decimal
    margen_contribucion: Decimal
    mc_porcentaje: Decimal
    costos_fijos: Decimal
    punto_equilibrio: Decimal
    diferencia: Decimal
    margen_seguridad: Decimal

    @property
    def alcanzable(self):
        return self.mc_porcentaje > 0

    @property
    def estado(self):
        if not self.alcanzable and self.costos_fijos:
            return "Sin punto de equilibrio: el margen de contribución no es positivo"
        if self.diferencia >= 0:
            return "Por encima del punto de equilibrio"
        return "Por debajo del punto de equilibrio"


def _punto_equilibrio(ventas, costos_variables, costos_fijos):
    margen = ventas - costos_variables
    mc_pct = dividir(margen, ventas)
    pe = dividir(costos_fijos, mc_pct)
    diferencia = ventas - pe
    return PuntoEquilibrio(
        ventas=ventas,
        costos_variables=costos_variables,
        margen_contribucion=margen,
        mc_porcentaje=mc_pct,
        costos_fijos=costos_fijos,
        punto_equilibrio=pe,
        diferencia=diferencia,
        margen_seguridad=dividir(diferencia, ventas),
    )


def punto_equilibrio(cxs: CostosPorServicio):
    """Devuelve (general, {servicio: PuntoEquilibrio})."""
    general = _punto_equilibrio(cxs.total_ventas, cxs.total_cv, cxs.costos_fijos)
    por_servicio = {
        s: _punto_equilibrio(cxs.ventas[s], cxs.total_costos_variables[s], cxs.costos_fijos_asignados[s])
        for s in SERVICIOS
    }
    return general, por_servicio


def ranking(valores: dict):
    """Ranking de mayor a menor (1 = mejor); empates comparten puesto, como JERARQUIA del Excel.

    Se compara con 6 decimales, para que dos servicios con la misma rentabilidad
    no queden en puestos distintos por una diferencia ínfima de redondeo.
    """
    redondeados = {k: round(v, 6) for k, v in valores.items()}
    return {k: 1 + sum(1 for otro in redondeados.values() if otro > v) for k, v in redondeados.items()}


# ---------------------------------------------------------------------------
# Atajos con base de datos
# ---------------------------------------------------------------------------


@dataclass
class Mes:
    periodo: object
    datos: DatosMes
    er: EstadoResultados
    cxs: CostosPorServicio


def calcular_mes(periodo) -> Mes:
    datos = DatosMes.desde_base(periodo)
    er = estado_resultados(datos)
    return Mes(periodo=periodo, datos=datos, er=er, cxs=costos_por_servicio(datos, er))


def calcular_periodos(periodos):
    return [calcular_mes(p) for p in periodos]

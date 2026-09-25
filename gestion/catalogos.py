"""Catálogos fijos de la empresa.

Los 9 servicios, las categorías de compra y los rubros de gastos manuales son
listas cerradas: se eligen de un desplegable y nunca se escriben a mano, para
que la clasificación no se rompa. Cambiar estos catálogos es un cambio de
programa (no de datos), porque las reglas de cálculo dependen de ellos.
"""
from django.db import models


class Servicio(models.TextChoices):
    # El orden es el de los centros de costo de facturación (CC2 a CC9),
    # igual que las columnas B a J de "Costos por Servicio" en el Excel.
    HIDROLAVADORAS = "HIDRO", "Hidrolavadoras Industriales"
    MODULOS = "MODULOS", "Módulos Transportables / Trailers"
    CLIMATIZACION = "CLIMA", "Climatización"
    OBRAS_CIVILES = "OBRAS", "Obras Civiles Menores"
    MANTENIMIENTO_EDILICIO = "MANT_EDIL", "Mantenimiento Edilicios"
    SOPORTE_PAE = "PAE", "Soporte a Producción PAE"
    SOPORTE_ALUVION_VISTA = "ALUVION", "Soporte a Producción Aluvión-Vista"
    CERCOS = "CERCOS", "Cercos Perimetrales y Corralitos"
    METALURGICA = "METAL", "Metalúrgica"


SERVICIOS = [s for s in Servicio]

# Servicios con cuadrilla fija propia: su mano de obra es la suma directa de
# las personas asignadas a ellos.
SERVICIOS_CUADRILLA_FIJA = [Servicio.SOPORTE_PAE, Servicio.CERCOS]

# Servicios que comparten el Pool Operativo: el costo del pool se reparte entre
# estos 7 en proporción a las ventas de cada uno en el mes.
SERVICIOS_POOL = [s for s in SERVICIOS if s not in SERVICIOS_CUADRILLA_FIJA]


class AsignacionPersonal(models.TextChoices):
    """Servicio Asignado en Personal y Nómina: un servicio, el pool o estructura."""

    HIDROLAVADORAS = Servicio.HIDROLAVADORAS.value, Servicio.HIDROLAVADORAS.label
    MODULOS = Servicio.MODULOS.value, Servicio.MODULOS.label
    CLIMATIZACION = Servicio.CLIMATIZACION.value, Servicio.CLIMATIZACION.label
    OBRAS_CIVILES = Servicio.OBRAS_CIVILES.value, Servicio.OBRAS_CIVILES.label
    MANTENIMIENTO_EDILICIO = Servicio.MANTENIMIENTO_EDILICIO.value, Servicio.MANTENIMIENTO_EDILICIO.label
    SOPORTE_PAE = Servicio.SOPORTE_PAE.value, Servicio.SOPORTE_PAE.label
    SOPORTE_ALUVION_VISTA = Servicio.SOPORTE_ALUVION_VISTA.value, Servicio.SOPORTE_ALUVION_VISTA.label
    CERCOS = Servicio.CERCOS.value, Servicio.CERCOS.label
    METALURGICA = Servicio.METALURGICA.value, Servicio.METALURGICA.label
    POOL = "POOL", (
        "Pool Operativo (Hidrolavadoras+Módulos+Climatización+Obras Civiles+"
        "Mant. Edilicios+Metalúrgica+Aluvión-Vista)"
    )
    ADMINISTRACION = "ADMIN", "Administración (estructura general)"


class CategoriaCompra(models.TextChoices):
    MATERIALES = "MATERIALES", "Materiales e Insumos"
    COMBUSTIBLE = "COMBUSTIBLE", "Combustible"
    MANTENIMIENTO_EQUIPOS = "MANT_EQUIPOS", "Mantenimiento de Equipos"
    OTROS_COSTOS_DIRECTOS = "OTROS_DIRECTOS", "Otros Costos Directos"
    OTROS_EGRESOS = "OTROS_EGRESOS", "Otros Egresos (no corresponde a Costos por Servicio)"


# Categorías que son costo de prestar los servicios (entran a Costos por Servicio).
CATEGORIAS_COSTO_DIRECTO = [
    CategoriaCompra.MATERIALES,
    CategoriaCompra.COMBUSTIBLE,
    CategoriaCompra.MANTENIMIENTO_EQUIPOS,
    CategoriaCompra.OTROS_COSTOS_DIRECTOS,
]


class ServicioCompra(models.TextChoices):
    """Servicio Asignado de una factura de compra."""

    HIDROLAVADORAS = Servicio.HIDROLAVADORAS.value, Servicio.HIDROLAVADORAS.label
    MODULOS = Servicio.MODULOS.value, Servicio.MODULOS.label
    CLIMATIZACION = Servicio.CLIMATIZACION.value, Servicio.CLIMATIZACION.label
    OBRAS_CIVILES = Servicio.OBRAS_CIVILES.value, Servicio.OBRAS_CIVILES.label
    MANTENIMIENTO_EDILICIO = Servicio.MANTENIMIENTO_EDILICIO.value, Servicio.MANTENIMIENTO_EDILICIO.label
    SOPORTE_PAE = Servicio.SOPORTE_PAE.value, Servicio.SOPORTE_PAE.label
    SOPORTE_ALUVION_VISTA = Servicio.SOPORTE_ALUVION_VISTA.value, Servicio.SOPORTE_ALUVION_VISTA.label
    CERCOS = Servicio.CERCOS.value, Servicio.CERCOS.label
    METALURGICA = Servicio.METALURGICA.value, Servicio.METALURGICA.label
    GENERAL = "GENERAL", "GENERAL (a prorratear por ventas)"
    NO_APLICA = "NA", "N/A — Otros Egresos (no aplica)"


class GrupoRubro(models.TextChoices):
    GASTO_OPERATIVO = "GO", "Gastos Operativos"
    GASTO_BANCARIO = "GB", "Gastos Bancarios y Financieros"
    OTRO_INGRESO = "OI", "Otros Ingresos"
    OTRO_EGRESO = "OE", "Otros Egresos (no operativos)"
    GANANCIAS = "IG", "Impuesto a las Ganancias"


class RubroGasto(models.TextChoices):
    """Rubros que se cargan a mano, ítem por ítem (no salen de ningún registro)."""

    ALQUILERES = "ALQUILERES", "Alquileres"
    SERVICIOS = "SERVICIOS", "Servicios (luz, gas, internet, etc.)"
    SEGUROS = "SEGUROS", "Seguros"
    IMPUESTOS_TASAS = "IMPUESTOS", "Impuestos y Tasas"
    OTROS_GASTOS_OPERATIVOS = "OTROS_GO", "Otros Gastos Operativos"
    LEASING = "LEASING", "Leasing Vehículos/Equipos"
    PLANES_PAGO = "PLANES_PAGO", "Cuotas Planes de Pago"
    COMISIONES_BANCARIAS = "COMISIONES", "Comisiones Bancarias"
    INTERESES = "INTERESES", "Intereses por Financiación"
    IMPUESTO_DEBITOS_CREDITOS = "LEY_25413", "Impuesto a los Créditos y Débitos (Ley 25.413)"
    OTROS_INGRESOS = "OTROS_INGRESOS", "Otros Ingresos"
    OTROS_EGRESOS_NO_OPERATIVOS = "OTROS_EGRESOS_NO", "Otros Egresos (no operativos)"
    IMPUESTO_GANANCIAS = "GANANCIAS", "Impuesto a las Ganancias (estimado)"


GRUPO_DE_RUBRO = {
    RubroGasto.ALQUILERES: GrupoRubro.GASTO_OPERATIVO,
    RubroGasto.SERVICIOS: GrupoRubro.GASTO_OPERATIVO,
    RubroGasto.SEGUROS: GrupoRubro.GASTO_OPERATIVO,
    RubroGasto.IMPUESTOS_TASAS: GrupoRubro.GASTO_OPERATIVO,
    RubroGasto.OTROS_GASTOS_OPERATIVOS: GrupoRubro.GASTO_OPERATIVO,
    RubroGasto.LEASING: GrupoRubro.GASTO_OPERATIVO,
    RubroGasto.PLANES_PAGO: GrupoRubro.GASTO_OPERATIVO,
    RubroGasto.COMISIONES_BANCARIAS: GrupoRubro.GASTO_BANCARIO,
    RubroGasto.INTERESES: GrupoRubro.GASTO_BANCARIO,
    RubroGasto.IMPUESTO_DEBITOS_CREDITOS: GrupoRubro.GASTO_BANCARIO,
    RubroGasto.OTROS_INGRESOS: GrupoRubro.OTRO_INGRESO,
    RubroGasto.OTROS_EGRESOS_NO_OPERATIVOS: GrupoRubro.OTRO_EGRESO,
    RubroGasto.IMPUESTO_GANANCIAS: GrupoRubro.GANANCIAS,
}


class ModoAsignacion(models.TextChoices):
    AUTOMATICO = "AUTO", "Automático (por Ventas)"
    MANUAL = "MANUAL", "Manual"


MESES = [
    (1, "Enero"), (2, "Febrero"), (3, "Marzo"), (4, "Abril"), (5, "Mayo"), (6, "Junio"),
    (7, "Julio"), (8, "Agosto"), (9, "Septiembre"), (10, "Octubre"), (11, "Noviembre"), (12, "Diciembre"),
]
NOMBRE_MES = dict(MESES)
MES_POR_NOMBRE = {nombre: numero for numero, nombre in MESES}

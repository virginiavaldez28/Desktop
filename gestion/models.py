"""Modelo de datos.

Sólo se guardan datos de carga: el período (mes) y su configuración, las tres
tablas de carga (Personal y Nómina, Registro de Compras, Registro de Ventas) y
los gastos que se cargan a mano ítem por ítem (Apertura de Costos y Gastos y
Gastos Bancarios). Los reportes no se guardan: se calculan cada vez en
`gestion/calculos.py`, así nunca quedan desactualizados.
"""
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator, RegexValidator
from django.db import models
from django.db.models import Sum
from simple_history.models import HistoricalRecords

from .catalogos import (
    NOMBRE_MES,
    SERVICIOS,
    AsignacionPersonal,
    CategoriaCompra,
    MESES,
    ModoAsignacion,
    RubroGasto,
    Servicio,
    ServicioCompra,
)

CIEN = Decimal("100")


def campo_monto(verbose_name, **kwargs):
    return models.DecimalField(verbose_name, max_digits=16, decimal_places=2, **kwargs)


class Auditable(models.Model):
    """Quién cargó y quién modificó por última vez cada renglón, y cuándo.

    El detalle completo de cada cambio (valor anterior y nuevo) queda además en
    el historial de cada registro (botón "Historial" en la pantalla de carga).
    """

    creado_en = models.DateTimeField("cargado el", auto_now_add=True)
    creado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, verbose_name="cargado por", on_delete=models.PROTECT,
        null=True, blank=True, editable=False, related_name="+",
    )
    modificado_en = models.DateTimeField("modificado el", auto_now=True)
    modificado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, verbose_name="modificado por", on_delete=models.PROTECT,
        null=True, blank=True, editable=False, related_name="+",
    )

    class Meta:
        abstract = True


# ---------------------------------------------------------------------------
# Período (mes) y su configuración
# ---------------------------------------------------------------------------


class PeriodoQuerySet(models.QuerySet):
    def entre(self, desde, hasta):
        """Períodos entre dos períodos (inclusive), en orden cronológico."""
        clave_desde = desde.anio * 100 + desde.mes
        clave_hasta = hasta.anio * 100 + hasta.mes
        return (
            self.annotate(orden_mes=models.F("anio") * 100 + models.F("mes"))
            .filter(orden_mes__gte=clave_desde, orden_mes__lte=clave_hasta)
            .order_by("anio", "mes")
        )


class Periodo(Auditable):
    anio = models.PositiveSmallIntegerField("año", validators=[MinValueValidator(2000), MaxValueValidator(2100)])
    mes = models.PositiveSmallIntegerField("mes", choices=MESES)
    modo_asignacion = models.CharField(
        "% de asignación de costos fijos",
        max_length=10,
        choices=ModoAsignacion.choices,
        default=ModoAsignacion.AUTOMATICO,
        help_text=(
            "Automático: cada servicio recibe según su participación en las Ventas del mes. "
            "Manual: se usan los % cargados abajo (deben sumar 100%)."
        ),
    )
    cerrado = models.BooleanField(
        "mes cerrado",
        default=False,
        help_text="Un mes cerrado ya no se puede modificar, salvo por un Administrador.",
    )
    saldo_proveedores = campo_monto(
        "saldo de proveedores al cierre del mes",
        null=True,
        blank=True,
        help_text="Dato informativo (memo del Estado de Resultados). No forma parte del resultado.",
    )
    observaciones = models.TextField(blank=True)

    history = HistoricalRecords()
    objects = PeriodoQuerySet.as_manager()

    class Meta:
        verbose_name = "período (mes)"
        verbose_name_plural = "períodos (meses)"
        ordering = ["-anio", "-mes"]
        constraints = [models.UniqueConstraint(fields=["anio", "mes"], name="periodo_unico")]
        permissions = [("ver_reportes", "Puede ver los reportes calculados")]

    def __str__(self):
        return f"{NOMBRE_MES[self.mes]} {self.anio}"

    @property
    def clave(self):
        """Identificador para las direcciones de los reportes, ej. "2026-07"."""
        return f"{self.anio}-{self.mes:02d}"

    @property
    def nombre_corto(self):
        return f"{NOMBRE_MES[self.mes][:3]} {self.anio}"

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        # Deja preparados los 9 renglones de % manual (en 0) para que se puedan completar.
        existentes = set(self.asignaciones_manuales.values_list("servicio", flat=True))
        AsignacionManual.objects.bulk_create(
            [AsignacionManual(periodo=self, servicio=s) for s in SERVICIOS if s.value not in existentes]
        )


class AsignacionManual(models.Model):
    """% de asignación de costos fijos cargado a mano (sólo se usa en modo Manual)."""

    periodo = models.ForeignKey(Periodo, on_delete=models.CASCADE, related_name="asignaciones_manuales")
    servicio = models.CharField(max_length=20, choices=Servicio.choices)
    porcentaje = models.DecimalField(
        "% manual",
        max_digits=6,
        decimal_places=3,
        default=Decimal("0"),
        validators=[MinValueValidator(Decimal("0")), MaxValueValidator(CIEN)],
    )

    history = HistoricalRecords()

    class Meta:
        verbose_name = "% manual de asignación"
        verbose_name_plural = "% manuales de asignación (sólo si el modo es Manual)"
        ordering = ["periodo", "id"]
        constraints = [models.UniqueConstraint(fields=["periodo", "servicio"], name="asignacion_manual_unica")]

    def __str__(self):
        return f"{self.get_servicio_display()}: {self.porcentaje}%"


# ---------------------------------------------------------------------------
# Catálogos editables: personas, clientes y proveedores
# ---------------------------------------------------------------------------

validar_cuil = RegexValidator(r"^\d{11}$", "El CUIL/CUIT debe tener 11 dígitos, sin guiones.")


class Persona(Auditable):
    apellido_nombre = models.CharField("apellido y nombre", max_length=200)
    cuil = models.CharField(
        "CUIL", max_length=11, blank=True, validators=[validar_cuil],
        help_text="11 dígitos sin guiones. Puede quedar vacío para terceros que facturan (ej. choferes).",
    )
    activa = models.BooleanField("activa", default=True, help_text="Desmarcar cuando la persona se da de baja.")
    observaciones = models.TextField(blank=True)

    history = HistoricalRecords()

    class Meta:
        verbose_name = "persona"
        verbose_name_plural = "personas"
        ordering = ["apellido_nombre"]
        constraints = [
            models.UniqueConstraint(fields=["cuil"], condition=~models.Q(cuil=""), name="cuil_unico"),
        ]

    def __str__(self):
        return self.apellido_nombre


class Cliente(Auditable):
    nombre = models.CharField(max_length=200, unique=True)
    cuit = models.CharField("CUIT", max_length=11, blank=True, validators=[validar_cuil])
    observaciones = models.TextField(blank=True)

    history = HistoricalRecords()

    class Meta:
        verbose_name = "cliente"
        verbose_name_plural = "clientes"
        ordering = ["nombre"]

    def __str__(self):
        return self.nombre


class Proveedor(Auditable):
    nombre = models.CharField(max_length=200, unique=True)
    cuit = models.CharField("CUIT", max_length=11, blank=True, validators=[validar_cuil])
    observaciones = models.TextField(blank=True)

    history = HistoricalRecords()

    class Meta:
        verbose_name = "proveedor"
        verbose_name_plural = "proveedores"
        ordering = ["nombre"]

    def __str__(self):
        return self.nombre


# ---------------------------------------------------------------------------
# Tablas de carga
# ---------------------------------------------------------------------------


class LiquidacionNomina(Auditable):
    """Personal y Nómina: un renglón por persona, por mes y por servicio asignado."""

    persona = models.ForeignKey(Persona, on_delete=models.PROTECT, related_name="liquidaciones")
    periodo = models.ForeignKey(Periodo, verbose_name="mes", on_delete=models.PROTECT, related_name="nomina")
    mano_obra_directa = models.BooleanField(
        "¿mano de obra directa?",
        default=True,
        help_text='"No" = estructura de Administración.',
    )
    asignacion = models.CharField(
        "servicio asignado", max_length=20, choices=AsignacionPersonal.choices,
    )
    porcentaje_afectacion = models.DecimalField(
        "% de afectación a ese servicio",
        max_digits=6,
        decimal_places=2,
        default=CIEN,
        validators=[MinValueValidator(Decimal("0")), MaxValueValidator(CIEN)],
        help_text="Entre 0 y 100. Si la persona se reparte entre dos servicios, cargá un renglón por cada uno.",
    )
    regimen = models.CharField(
        "régimen / vínculo", max_length=200, blank=True,
        help_text='Informativo. Ej.: "Petroleros Privados", "UOCRA", "Socio de la empresa".',
    )
    haberes = campo_monto("haberes (neto de recibo)", default=Decimal("0"))
    contribuciones_patronales = campo_monto("contribuciones patronales", default=Decimal("0"))
    sindicato_mutual = campo_monto(
        "sindicato y mutual", default=Decimal("0"),
        help_text="Importe final ya calculado por quien carga (según recibo y planilla del sindicato).",
    )
    honorarios = campo_monto("honorarios (monotributistas)", default=Decimal("0"))
    observaciones = models.TextField(blank=True)

    history = HistoricalRecords()

    class Meta:
        verbose_name = "renglón de nómina"
        verbose_name_plural = "personal y nómina"
        ordering = ["-periodo__anio", "-periodo__mes", "persona__apellido_nombre", "asignacion"]
        constraints = [
            models.UniqueConstraint(fields=["persona", "periodo", "asignacion"], name="nomina_unica"),
        ]

    def __str__(self):
        return f"{self.persona} — {self.periodo} — {self.get_asignacion_display()}"

    @property
    def total_mes(self):
        return self.haberes + self.contribuciones_patronales + self.sindicato_mutual + self.honorarios

    @property
    def asignado_servicio(self):
        return self.total_mes * self.porcentaje_afectacion / CIEN

    def clean(self):
        errores = {}
        es_admin = self.asignacion == AsignacionPersonal.ADMINISTRACION
        if es_admin and self.mano_obra_directa:
            errores["mano_obra_directa"] = (
                'Si el Servicio Asignado es "Administración", ¿Mano de Obra Directa? tiene que ser "No".'
            )
        if not es_admin and self.asignacion and not self.mano_obra_directa:
            errores["asignacion"] = (
                'Si ¿Mano de Obra Directa? es "No" (estructura), el Servicio Asignado tiene que ser "Administración".'
            )
        if self.persona_id and self.periodo_id and self.porcentaje_afectacion is not None:
            otros = (
                LiquidacionNomina.objects.filter(persona_id=self.persona_id, periodo_id=self.periodo_id)
                .exclude(pk=self.pk)
                .aggregate(total=Sum("porcentaje_afectacion"))["total"]
                or Decimal("0")
            )
            if otros + self.porcentaje_afectacion > CIEN:
                errores["porcentaje_afectacion"] = (
                    f"Esta persona ya tiene {otros:.2f}% asignado en este mes en otros renglones; "
                    f"con este renglón superaría el 100%."
                )
        if errores:
            raise ValidationError(errores)


class Compra(Auditable):
    """Registro de Compras: un renglón por factura (o nota de crédito, en negativo)."""

    fecha = models.DateField()
    proveedor = models.ForeignKey(Proveedor, on_delete=models.PROTECT, related_name="compras")
    tipo_comprobante = models.CharField(
        "tipo de comprobante", max_length=60, help_text='Ej.: "Factura A", "Factura B", "Nota de Crédito A".',
    )
    punto_venta = models.PositiveIntegerField("punto de venta")
    numero = models.PositiveBigIntegerField("N° de factura")
    periodo = models.ForeignKey(Periodo, verbose_name="mes", on_delete=models.PROTECT, related_name="compras")
    categoria = models.CharField("categoría", max_length=20, choices=CategoriaCompra.choices)
    servicio_asignado = models.CharField("servicio asignado", max_length=20, choices=ServicioCompra.choices)
    monto = campo_monto("monto", help_text="Las notas de crédito se cargan en negativo.")
    observaciones = models.TextField(blank=True)

    history = HistoricalRecords()

    class Meta:
        verbose_name = "factura de compra"
        verbose_name_plural = "registro de compras"
        ordering = ["-fecha", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["proveedor", "tipo_comprobante", "punto_venta", "numero"], name="compra_unica",
            ),
        ]

    def __str__(self):
        return f"{self.tipo_comprobante} {self.punto_venta:05d}-{self.numero:08d} — {self.proveedor}"

    def clean(self):
        es_otros_egresos = self.categoria == CategoriaCompra.OTROS_EGRESOS
        es_no_aplica = self.servicio_asignado == ServicioCompra.NO_APLICA
        if es_otros_egresos and not es_no_aplica:
            raise ValidationError({
                "servicio_asignado": 'Con Categoría "Otros Egresos" el Servicio Asignado tiene que ser "N/A — Otros Egresos".'
            })
        if es_no_aplica and not es_otros_egresos:
            raise ValidationError({
                "servicio_asignado": '"N/A — Otros Egresos" sólo corresponde con Categoría "Otros Egresos". '
                'Si la factura es de varios servicios, elegí "GENERAL (a prorratear por ventas)".'
            })


class Venta(Auditable):
    """Registro de Ventas: un renglón por factura (o nota de crédito, en negativo)."""

    fecha = models.DateField()
    cliente = models.ForeignKey(Cliente, on_delete=models.PROTECT, related_name="ventas")
    tipo_comprobante = models.CharField(
        "tipo de comprobante", max_length=60, help_text='Ej.: "Factura A", "Nota de Crédito A".',
    )
    punto_venta = models.PositiveIntegerField("punto de venta")
    numero = models.PositiveBigIntegerField("N° de factura")
    periodo = models.ForeignKey(Periodo, verbose_name="mes", on_delete=models.PROTECT, related_name="ventas")
    servicio = models.CharField(max_length=20, choices=Servicio.choices)
    monto = campo_monto("monto", help_text="Las notas de crédito se cargan en negativo.")
    observaciones = models.TextField(blank=True)

    history = HistoricalRecords()

    class Meta:
        verbose_name = "factura de venta"
        verbose_name_plural = "registro de ventas"
        ordering = ["-fecha", "-id"]
        constraints = [
            models.UniqueConstraint(fields=["tipo_comprobante", "punto_venta", "numero"], name="venta_unica"),
        ]

    def __str__(self):
        return f"{self.tipo_comprobante} {self.punto_venta:05d}-{self.numero:08d} — {self.cliente}"


class GastoManual(Auditable):
    """Ítems que no salen de ningún registro: Alquileres, Seguros, Leasing, Gastos Bancarios, etc."""

    periodo = models.ForeignKey(Periodo, verbose_name="mes", on_delete=models.PROTECT, related_name="gastos_manuales")
    rubro = models.CharField(max_length=20, choices=RubroGasto.choices)
    concepto = models.CharField(
        max_length=200, help_text='Descripción del ítem, ej.: "Banco Provincia cta 1 (cuota + seguro + patente)".',
    )
    monto = campo_monto("monto")
    observaciones = models.TextField(blank=True)

    history = HistoricalRecords()

    class Meta:
        verbose_name = "gasto cargado a mano"
        verbose_name_plural = "apertura de gastos (carga manual)"
        ordering = ["-periodo__anio", "-periodo__mes", "rubro", "concepto"]

    def __str__(self):
        return f"{self.get_rubro_display()} — {self.concepto} — {self.periodo}"

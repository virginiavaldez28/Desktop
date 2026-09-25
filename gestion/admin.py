"""Pantallas de carga (formularios, listados, filtros, historial de cambios)."""
from decimal import Decimal

from django import forms
from django.contrib import admin, messages
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.db import models
from django.urls import reverse
from django.utils.html import format_html
from simple_history.admin import SimpleHistoryAdmin

from .catalogos import AsignacionPersonal, ModoAsignacion
from .formato import moneda
from .models import (
    AsignacionManual,
    Cliente,
    Compra,
    GastoManual,
    LiquidacionNomina,
    Periodo,
    Persona,
    Proveedor,
    Venta,
)
from .roles import es_administrador

admin.site.site_header = "Grupo Valpob S.R.L. — Gestión Financiera"
admin.site.site_title = "Valpob"
admin.site.index_title = "Carga de datos"
admin.site.site_url = "/"

AYUDA_MONTO = "Formato: 1.234.567,89 (miles con punto, decimales con coma)."


class BaseAdmin(SimpleHistoryAdmin):
    """Comportamiento común: montos en formato argentino y registro de quién cargó/modificó."""

    formfield_overrides = {models.DecimalField: {"localize": True}}
    campos_auditoria = ("creado_por", "creado_en", "modificado_por", "modificado_en")

    def get_readonly_fields(self, request, obj=None):
        return tuple(super().get_readonly_fields(request, obj)) + self.campos_auditoria

    def get_fieldsets(self, request, obj=None):
        fieldsets = super().get_fieldsets(request, obj)
        if obj is None:
            # Al cargar un renglón nuevo, la auditoría todavía no tiene datos.
            limpios = []
            for nombre, opciones in fieldsets:
                campos = [f for f in opciones["fields"] if f not in self.campos_auditoria]
                if campos:
                    limpios.append((nombre, {**opciones, "fields": campos}))
            return limpios
        return fieldsets

    def formfield_for_dbfield(self, db_field, request, **kwargs):
        campo = super().formfield_for_dbfield(db_field, request, **kwargs)
        if isinstance(db_field, models.DecimalField) and campo is not None and db_field.decimal_places == 2:
            campo.help_text = f"{db_field.help_text} {AYUDA_MONTO}".strip()
        return campo

    def save_model(self, request, obj, form, change):
        if not change:
            obj.creado_por = request.user
        obj.modificado_por = request.user
        super().save_model(request, obj, form, change)


class CargaMensualAdmin(BaseAdmin):
    """Registros que pertenecen a un mes: respetan el cierre del mes."""

    total_campo = None  # Nombre del campo a totalizar en el listado.
    list_per_page = 100
    list_select_related = ("periodo",)

    def _mes_cerrado(self, request, obj):
        return obj is not None and obj.periodo.cerrado and not es_administrador(request.user)

    def has_change_permission(self, request, obj=None):
        return super().has_change_permission(request, obj) and not self._mes_cerrado(request, obj)

    def has_delete_permission(self, request, obj=None):
        return super().has_delete_permission(request, obj) and not self._mes_cerrado(request, obj)

    def get_form(self, request, obj=None, **kwargs):
        form = super().get_form(request, obj, **kwargs)
        usuario_es_admin = es_administrador(request.user)

        class FormularioConCierre(form):
            def clean(self):
                datos = super().clean()
                periodo = datos.get("periodo")
                if periodo and periodo.cerrado and not usuario_es_admin:
                    raise ValidationError(f"{periodo} está cerrado: sólo un Administrador puede cargar o modificar.")
                return datos

        return FormularioConCierre

    def changelist_view(self, request, extra_context=None):
        respuesta = super().changelist_view(request, extra_context)
        contexto = getattr(respuesta, "context_data", None)
        if self.total_campo and contexto and "cl" in contexto:
            valores = contexto["cl"].queryset.values_list(self.total_campo, flat=True)
            total = sum(valores, Decimal("0"))
            contexto["total_filtrado"] = moneda(total)
        return respuesta


# ---------------------------------------------------------------------------
# Período (mes)
# ---------------------------------------------------------------------------


class AsignacionManualFormSet(forms.BaseInlineFormSet):
    def clean(self):
        super().clean()
        if self.instance.modo_asignacion != ModoAsignacion.MANUAL:
            return
        porcentajes = [f.cleaned_data.get("porcentaje") or Decimal("0") for f in self.forms if f.cleaned_data]
        if not porcentajes:
            raise ValidationError(
                'Para usar el modo "Manual", primero guardá el mes en modo Automático y después completá los %.'
            )
        total = sum(porcentajes, Decimal("0"))
        if total != Decimal("100"):
            raise ValidationError(f"Los % manuales tienen que sumar 100%. Hoy suman {total}%.")


class AsignacionManualInline(admin.TabularInline):
    model = AsignacionManual
    formset = AsignacionManualFormSet
    formfield_overrides = {models.DecimalField: {"localize": True}}
    fields = ("servicio", "porcentaje")
    readonly_fields = ("servicio",)
    extra = 0
    can_delete = False
    max_num = 9

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Periodo)
class PeriodoAdmin(BaseAdmin):
    list_display = ("__str__", "modo_asignacion", "estado", "renglones_nomina", "facturas_venta", "facturas_compra")
    list_filter = ("anio", "cerrado", "modo_asignacion")
    fieldsets = (
        (None, {"fields": ("anio", "mes", "cerrado", "observaciones")}),
        ("% de asignación de costos fijos", {"fields": ("modo_asignacion",)}),
        ("Memo del Estado de Resultados", {"fields": ("saldo_proveedores",)}),
        ("Auditoría", {"fields": BaseAdmin.campos_auditoria, "classes": ("collapse",)}),
    )
    inlines = [AsignacionManualInline]
    actions = ["copiar_nomina_mes_anterior", "cerrar_meses", "reabrir_meses"]

    @admin.display(description="estado")
    def estado(self, obj):
        return "Cerrado" if obj.cerrado else "Abierto"

    @admin.display(description="renglones de nómina")
    def renglones_nomina(self, obj):
        url = reverse("admin:gestion_liquidacionnomina_changelist") + f"?periodo__id__exact={obj.pk}"
        return format_html('<a href="{}">{}</a>', url, obj.nomina.count())

    @admin.display(description="facturas de venta")
    def facturas_venta(self, obj):
        url = reverse("admin:gestion_venta_changelist") + f"?periodo__id__exact={obj.pk}"
        return format_html('<a href="{}">{}</a>', url, obj.ventas.count())

    @admin.display(description="facturas de compra")
    def facturas_compra(self, obj):
        url = reverse("admin:gestion_compra_changelist") + f"?periodo__id__exact={obj.pk}"
        return format_html('<a href="{}">{}</a>', url, obj.compras.count())

    @admin.action(description="Copiar la nómina del mes anterior (con importes en 0, para completar)")
    def copiar_nomina_mes_anterior(self, request, queryset):
        for periodo in queryset:
            if periodo.nomina.exists():
                self.message_user(request, f"{periodo} ya tiene nómina cargada: no se copió nada.", messages.WARNING)
                continue
            anterior = (
                Periodo.objects.filter(models.Q(anio__lt=periodo.anio) | models.Q(anio=periodo.anio, mes__lt=periodo.mes))
                .order_by("-anio", "-mes")
                .first()
            )
            if anterior is None or not anterior.nomina.exists():
                self.message_user(request, f"No hay un mes anterior con nómina para copiar a {periodo}.", messages.WARNING)
                continue
            nuevos = [
                LiquidacionNomina(
                    persona=r.persona,
                    periodo=periodo,
                    mano_obra_directa=r.mano_obra_directa,
                    asignacion=r.asignacion,
                    porcentaje_afectacion=r.porcentaje_afectacion,
                    regimen=r.regimen,
                    observaciones=f"Copiado de {anterior}: completar los importes del mes.",
                    creado_por=request.user,
                    modificado_por=request.user,
                )
                for r in anterior.nomina.select_related("persona").filter(persona__activa=True)
            ]
            LiquidacionNomina.objects.bulk_create(nuevos)
            self.message_user(
                request,
                f"Se copiaron {len(nuevos)} renglones de {anterior} a {periodo} con importes en 0. "
                "Completá Haberes, Contribuciones, Sindicato y Honorarios de cada uno.",
                messages.SUCCESS,
            )

    @admin.action(description="Cerrar los meses elegidos (ya no se podrán modificar)")
    def cerrar_meses(self, request, queryset):
        queryset.update(cerrado=True)
        self.message_user(request, "Meses cerrados.", messages.SUCCESS)

    @admin.action(description="Reabrir los meses elegidos")
    def reabrir_meses(self, request, queryset):
        queryset.update(cerrado=False)
        self.message_user(request, "Meses reabiertos.", messages.SUCCESS)


# ---------------------------------------------------------------------------
# Catálogos editables
# ---------------------------------------------------------------------------


@admin.register(Persona)
class PersonaAdmin(BaseAdmin):
    list_display = ("apellido_nombre", "cuil", "activa")
    list_filter = ("activa",)
    search_fields = ("apellido_nombre", "cuil")


@admin.register(Cliente)
class ClienteAdmin(BaseAdmin):
    list_display = ("nombre", "cuit")
    search_fields = ("nombre", "cuit")


@admin.register(Proveedor)
class ProveedorAdmin(BaseAdmin):
    list_display = ("nombre", "cuit")
    search_fields = ("nombre", "cuit")


# ---------------------------------------------------------------------------
# Tablas de carga
# ---------------------------------------------------------------------------


@admin.register(LiquidacionNomina)
class LiquidacionNominaAdmin(CargaMensualAdmin):
    total_campo = None  # el total se calcula aparte (es una columna calculada)
    list_display = (
        "persona", "periodo", "mod", "asignacion_corta", "porcentaje_afectacion",
        "total_mes_fmt", "asignado_fmt",
    )
    list_filter = ("periodo", "mano_obra_directa", "asignacion")
    search_fields = ("persona__apellido_nombre", "persona__cuil", "regimen", "observaciones")
    autocomplete_fields = ("persona",)
    list_select_related = ("periodo", "persona")
    fieldsets = (
        (None, {"fields": ("persona", "periodo", "mano_obra_directa", "asignacion", "porcentaje_afectacion", "regimen")}),
        ("Costo del mes", {"fields": ("haberes", "contribuciones_patronales", "sindicato_mutual", "honorarios")}),
        (None, {"fields": ("observaciones",)}),
        ("Auditoría", {"fields": BaseAdmin.campos_auditoria, "classes": ("collapse",)}),
    )

    @admin.display(description="¿MOD?", ordering="mano_obra_directa")
    def mod(self, obj):
        return "Sí" if obj.mano_obra_directa else "No"

    @admin.display(description="servicio asignado", ordering="asignacion")
    def asignacion_corta(self, obj):
        if obj.asignacion == AsignacionPersonal.POOL:
            return "Pool Operativo"
        if obj.asignacion == AsignacionPersonal.ADMINISTRACION:
            return "Administración"
        return obj.get_asignacion_display()

    @admin.display(description="total del mes")
    def total_mes_fmt(self, obj):
        return moneda(obj.total_mes)

    @admin.display(description="$ asignado al servicio")
    def asignado_fmt(self, obj):
        return moneda(obj.asignado_servicio)

    def changelist_view(self, request, extra_context=None):
        respuesta = super().changelist_view(request, extra_context)
        contexto = getattr(respuesta, "context_data", None)
        if contexto and "cl" in contexto:
            total = sum((r.asignado_servicio for r in contexto["cl"].queryset), Decimal("0"))
            contexto["total_filtrado"] = moneda(total)
        return respuesta


@admin.register(Compra)
class CompraAdmin(CargaMensualAdmin):
    total_campo = "monto"
    list_display = (
        "fecha", "proveedor", "tipo_comprobante", "punto_venta", "numero", "periodo",
        "categoria", "servicio_asignado", "monto_fmt",
    )
    list_filter = ("periodo", "categoria", "servicio_asignado")
    search_fields = ("proveedor__nombre", "numero", "observaciones")
    autocomplete_fields = ("proveedor",)
    list_select_related = ("periodo", "proveedor")
    date_hierarchy = "fecha"
    fieldsets = (
        ("Comprobante", {"fields": ("fecha", "proveedor", "tipo_comprobante", "punto_venta", "numero", "periodo")}),
        ("Clasificación", {"fields": ("categoria", "servicio_asignado", "monto", "observaciones")}),
        ("Auditoría", {"fields": BaseAdmin.campos_auditoria, "classes": ("collapse",)}),
    )

    @admin.display(description="monto", ordering="monto")
    def monto_fmt(self, obj):
        return moneda(obj.monto)


@admin.register(Venta)
class VentaAdmin(CargaMensualAdmin):
    total_campo = "monto"
    list_display = (
        "fecha", "cliente", "tipo_comprobante", "punto_venta", "numero", "periodo", "servicio", "monto_fmt",
    )
    list_filter = ("periodo", "servicio", "tipo_comprobante")
    search_fields = ("cliente__nombre", "numero", "observaciones")
    autocomplete_fields = ("cliente",)
    list_select_related = ("periodo", "cliente")
    date_hierarchy = "fecha"
    fieldsets = (
        ("Comprobante", {"fields": ("fecha", "cliente", "tipo_comprobante", "punto_venta", "numero", "periodo")}),
        ("Clasificación", {"fields": ("servicio", "monto", "observaciones")}),
        ("Auditoría", {"fields": BaseAdmin.campos_auditoria, "classes": ("collapse",)}),
    )

    @admin.display(description="monto", ordering="monto")
    def monto_fmt(self, obj):
        return moneda(obj.monto)


@admin.register(GastoManual)
class GastoManualAdmin(CargaMensualAdmin):
    total_campo = "monto"
    list_display = ("periodo", "rubro", "concepto", "monto_fmt")
    list_filter = ("periodo", "rubro")
    search_fields = ("concepto", "observaciones")
    fieldsets = (
        (None, {"fields": ("periodo", "rubro", "concepto", "monto", "observaciones")}),
        ("Auditoría", {"fields": BaseAdmin.campos_auditoria, "classes": ("collapse",)}),
    )

    @admin.display(description="monto", ordering="monto")
    def monto_fmt(self, obj):
        return moneda(obj.monto)


# ---------------------------------------------------------------------------
# Usuarios: todo usuario creado desde acá puede entrar a la aplicación.
# ---------------------------------------------------------------------------

admin.site.unregister(User)


@admin.register(User)
class UsuarioAdmin(UserAdmin):
    list_display = ("username", "first_name", "last_name", "email", "roles", "is_active")

    @admin.display(description="roles")
    def roles(self, obj):
        return ", ".join(obj.groups.values_list("name", flat=True)) or "—"

    def save_model(self, request, obj, form, change):
        obj.is_staff = True  # necesario para entrar a las pantallas de carga
        super().save_model(request, obj, form, change)

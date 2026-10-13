"""Nómina del mes: grilla editable (un renglón por persona y por servicio) y documentos de respaldo."""
from decimal import Decimal

from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.forms import modelformset_factory
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render

from .models import LiquidacionNomina, Periodo, Persona
from .roles import es_administrador, puede_ver_reportes
from .views import MENU_REPORTES

CAMPOS_IMPORTE = [
    "haberes", "haberes_pagados_en_el_mes", "contribuciones_patronales", "sindicato_mutual",
    "honorarios", "pagos_transferencia", "beneficios_adicionales",
]
CAMPOS = ["persona", "mano_obra_directa", "asignacion", "porcentaje_afectacion", "regimen", *CAMPOS_IMPORTE, "observaciones"]
TITULOS = {
    "haberes": "Haberes (bruto)",
    "haberes_pagados_en_el_mes": "1ª quincena (pagada en el mes)",
    "contribuciones_patronales": "Contribuciones (F.931)",
    "sindicato_mutual": "Sindicato (parte empresa)",
    "honorarios": "Honorarios",
    "pagos_transferencia": "Transferencias",
    "beneficios_adicionales": "Beneficios adicionales",
}


class RenglonForm(forms.ModelForm):
    class Meta:
        model = LiquidacionNomina
        fields = CAMPOS
        localized_fields = ["porcentaje_afectacion", *CAMPOS_IMPORTE]
        widgets = {
            "observaciones": forms.Textarea(attrs={"rows": 1}),
            "regimen": forms.TextInput(attrs={"size": 14}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["persona"].queryset = Persona.objects.order_by("apellido_nombre")
        for nombre in CAMPOS_IMPORTE + ["porcentaje_afectacion"]:
            self.fields[nombre].widget.attrs.update({"class": "importe", "inputmode": "decimal"})
            self.fields[nombre].required = False
        for nombre in CAMPOS_IMPORTE:
            self.fields[nombre].widget.attrs["data-columna"] = nombre

    def clean(self):
        datos = super().clean()
        for nombre in CAMPOS_IMPORTE:
            if datos.get(nombre) is None:
                datos[nombre] = Decimal("0")
                setattr(self.instance, nombre, Decimal("0"))
        if datos.get("porcentaje_afectacion") is None:
            datos["porcentaje_afectacion"] = Decimal("100")
        return datos

    def has_changed(self):
        # Un renglón nuevo sin persona elegida es un renglón vacío de la grilla: se ignora.
        if self.instance.pk is None and not self.data.get(self.add_prefix("persona")):
            return False
        return super().has_changed()


class RenglonesDelMes(forms.BaseModelFormSet):
    def __init__(self, *args, periodo=None, **kwargs):
        self.periodo = periodo
        super().__init__(*args, **kwargs)

    def _construct_form(self, i, **kwargs):
        form = super()._construct_form(i, **kwargs)
        form.instance.periodo = self.periodo  # las validaciones del modelo necesitan el mes
        form.instance._porcentaje_controlado_en_grilla = True
        return form

    def clean(self):
        # El % de afectación de cada persona se controla sumando lo que queda en la grilla, así se puede
        # pasar a alguien de 60/40 a 40/60, o borrar un renglón y agregar otro, en un solo guardado.
        super().clean()
        totales, formularios = {}, {}
        for form in self.forms:
            if not hasattr(form, "cleaned_data") or not form.has_changed() and form.instance.pk is None:
                continue
            if self.can_delete and self._should_delete_form(form):
                continue
            persona = form.cleaned_data.get("persona")
            if persona is None:
                continue
            totales[persona] = totales.get(persona, Decimal("0")) + (form.cleaned_data.get("porcentaje_afectacion") or Decimal("0"))
            formularios.setdefault(persona, []).append(form)
        for persona, total in totales.items():
            if total > Decimal("100"):
                for form in formularios[persona]:
                    form.add_error("porcentaje_afectacion", f"{persona} suma {total:.2f}% en este mes; no puede superar el 100%.")


RenglonesFormSet = modelformset_factory(
    LiquidacionNomina, form=RenglonForm, formset=RenglonesDelMes, extra=3, can_delete=True,
)


def _periodos():
    return list(Periodo.objects.order_by("anio", "mes"))


@login_required
def nomina_ultimo_mes(request):
    periodos = _periodos()
    if not periodos:
        return redirect("admin:gestion_periodo_changelist")
    p = periodos[-1]
    return redirect("nomina_mes", anio=p.anio, mes=p.mes)


@login_required
def nomina_mes(request, anio, mes):
    if not request.user.has_perm("gestion.view_liquidacionnomina"):
        raise PermissionDenied("No tenés permiso para ver la nómina.")
    periodo = get_object_or_404(Periodo, anio=anio, mes=mes)
    puede_editar = request.user.has_perm("gestion.change_liquidacionnomina") and (
        not periodo.cerrado or es_administrador(request.user)
    )
    renglones = (
        LiquidacionNomina.objects.filter(periodo=periodo)
        .select_related("persona")
        .order_by("persona__apellido_nombre", "asignacion")
    )
    if request.method == "POST":
        if not puede_editar:
            raise PermissionDenied("Este mes está cerrado o no tenés permiso para modificar la nómina.")
        formset = RenglonesFormSet(request.POST, queryset=renglones, periodo=periodo)
        if formset.is_valid():
            for form in formset.forms:
                if form in formset.deleted_forms or not form.has_changed():
                    continue
                renglon = form.instance
                if renglon.pk is None:
                    renglon.creado_por = request.user
                renglon.modificado_por = request.user
            formset.save()
            cambios = len(formset.changed_objects) + len(formset.new_objects) + len(formset.deleted_objects)
            messages.success(request, f"Nómina de {periodo} guardada ({cambios} renglones modificados).")
            return redirect("nomina_mes", anio=anio, mes=mes)
        messages.error(request, "Hay errores: revisá los renglones marcados en rojo. No se guardó nada.")
    else:
        formset = RenglonesFormSet(queryset=renglones, periodo=periodo)

    totales = {c: sum((getattr(r, c) for r in renglones), Decimal("0")) for c in CAMPOS_IMPORTE}
    total_costo = sum((r.total_mes for r in renglones), Decimal("0"))
    total_asignado = sum((r.asignado_servicio for r in renglones), Decimal("0"))
    return render(request, "gestion/nomina_mes.html", {
        "periodo": periodo,
        "periodos": _periodos(),
        "formset": formset,
        "puede_editar": puede_editar,
        "columnas": [(c, TITULOS[c]) for c in CAMPOS_IMPORTE],
        "totales": totales,
        "total_costo": total_costo,
        "total_asignado": total_asignado,
        "menu_reportes": MENU_REPORTES,
        "ve_reportes": puede_ver_reportes(request.user),
        "nombre": "nomina",
    })


# ---------------------------------------------------------------------------
# Documentos del mes (F.931, recibos, Libro de Sueldos, planillas sindicales)
# ---------------------------------------------------------------------------

from django.http import FileResponse  # noqa: E402
from django.views.decorators.http import require_POST  # noqa: E402

from . import documentos as docs  # noqa: E402
from .lectores import ErrorLectura, texto_pdf  # noqa: E402
from .models import DocumentoNomina  # noqa: E402


class DocumentoForm(forms.ModelForm):
    class Meta:
        model = DocumentoNomina
        fields = ["tipo", "archivo", "primera_quincena", "intereses", "observaciones"]
        localized_fields = ["intereses"]
        widgets = {"observaciones": forms.Textarea(attrs={"rows": 2})}

    def clean_archivo(self):
        archivo = self.cleaned_data["archivo"]
        if not archivo.name.lower().endswith(".pdf"):
            raise forms.ValidationError("El archivo tiene que ser un PDF.")
        return archivo

    def clean(self):
        datos = super().clean()
        if self.errors:
            return datos
        doc = DocumentoNomina(tipo=datos["tipo"], primera_quincena=datos.get("primera_quincena") or False,
                              intereses=datos.get("intereses") or Decimal("0"))
        try:
            self.lectura = docs.leer_documento(doc, texto=texto_pdf(datos["archivo"]))
        except ErrorLectura as error:
            raise forms.ValidationError(f"No pude leer el documento: {error}")
        except Exception as error:
            raise forms.ValidationError(f"El archivo no parece un PDF válido ({error}).")
        datos["archivo"].seek(0)
        return datos


def _contexto_mes(request, anio, mes, editar=False):
    if not request.user.has_perm("gestion.view_liquidacionnomina"):
        raise PermissionDenied("No tenés permiso para ver la nómina.")
    periodo = get_object_or_404(Periodo, anio=anio, mes=mes)
    puede_editar = request.user.has_perm("gestion.change_liquidacionnomina") and (
        not periodo.cerrado or es_administrador(request.user)
    )
    if editar and not puede_editar:
        raise PermissionDenied("Este mes está cerrado o no tenés permiso para modificar la nómina.")
    return periodo, puede_editar


@login_required
def nomina_documentos(request, anio, mes):
    periodo, puede_editar = _contexto_mes(request, anio, mes)
    if request.method == "POST":
        if not puede_editar:
            raise PermissionDenied("Este mes está cerrado o no tenés permiso para modificar la nómina.")
        form = DocumentoForm(request.POST, request.FILES)
        if form.is_valid():
            doc = form.save(commit=False)
            doc.periodo = periodo
            doc.creado_por = doc.modificado_por = request.user
            doc.save()
            messages.success(request, f"{doc.get_tipo_display()} subido: {form.lectura.resumen} "
                                      "Revisá los cambios y aplicalos en la nómina.")
            return redirect("nomina_documentos_aplicar", anio=anio, mes=mes, grupo=docs.GRUPO_DE_TIPO[doc.tipo])
    else:
        form = DocumentoForm()
    grupos = []
    for clave, g in docs.GRUPOS.items():
        grupos.append({"clave": clave, "titulo": g["titulo"],
                       "documentos": DocumentoNomina.objects.filter(periodo=periodo, tipo__in=g["tipos"]).select_related("creado_por")})
    return render(request, "gestion/nomina_documentos.html", {
        "periodo": periodo, "periodos": _periodos(), "form": form, "grupos": grupos, "puede_editar": puede_editar,
        "menu_reportes": MENU_REPORTES, "ve_reportes": puede_ver_reportes(request.user), "nombre": "nomina",
    })


@login_required
def nomina_documentos_aplicar(request, anio, mes, grupo):
    if grupo not in docs.GRUPOS:
        raise Http404
    periodo, puede_editar = _contexto_mes(request, anio, mes, editar=request.method == "POST")
    if request.method == "POST":
        cambiadas, _ = docs.aplicar(periodo, grupo, request.user)
        messages.success(request, f"{docs.GRUPOS[grupo]['titulo']}: se actualizaron {cambiadas} personas en la nómina de "
                                  f"{periodo}. Podés seguir modificando cualquier importe a mano.")
        return redirect("nomina_mes", anio=anio, mes=mes)
    return render(request, "gestion/nomina_documentos_aplicar.html", {
        "periodo": periodo, "prop": docs.propuesta(periodo, grupo), "grupo": grupo, "puede_editar": puede_editar,
        "menu_reportes": MENU_REPORTES, "ve_reportes": puede_ver_reportes(request.user), "nombre": "nomina",
    })


@login_required
def documento_descargar(request, pk):
    doc = get_object_or_404(DocumentoNomina, pk=pk)
    _contexto_mes(request, doc.periodo.anio, doc.periodo.mes)
    return FileResponse(doc.archivo.open("rb"), as_attachment=True, filename=doc.nombre_archivo)


@login_required
@require_POST
def documento_borrar(request, pk):
    doc = get_object_or_404(DocumentoNomina, pk=pk)
    periodo, _ = _contexto_mes(request, doc.periodo.anio, doc.periodo.mes, editar=True)
    doc.archivo.delete(save=False)
    doc.delete()
    messages.success(request, "Documento borrado. Los importes que ya se habían aplicado a la nómina no cambian.")
    return redirect("nomina_documentos", anio=periodo.anio, mes=periodo.mes)

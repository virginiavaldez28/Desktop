"""Grilla editable de la nómina del mes y reparto por persona de los documentos subidos."""
import shutil
import tempfile
from decimal import Decimal as D
from unittest import mock

from django.contrib.auth.models import Group, User
from django.core.files.base import ContentFile
from django.test import TestCase, override_settings

from gestion import documentos as docs
from gestion import lectores
from gestion.catalogos import AsignacionPersonal
from gestion.models import DocumentoNomina, LiquidacionNomina, Periodo, Persona
from gestion.roles import CARGA_PERSONAL, SOLO_LECTURA

MEDIA = tempfile.mkdtemp()


@override_settings(ALLOWED_HOSTS=["testserver"], MEDIA_ROOT=MEDIA)
class NominaTest(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(MEDIA, ignore_errors=True)

    def setUp(self):
        self.periodo = Periodo.objects.create(anio=2026, mes=8)
        self.ana = Persona.objects.create(apellido_nombre="Ana Uno", cuil="27111111111")
        self.beto = Persona.objects.create(apellido_nombre="Beto Dos", cuil="20222222222")
        base = dict(periodo=self.periodo, mano_obra_directa=True)
        self.r_ana = LiquidacionNomina.objects.create(persona=self.ana, asignacion=AsignacionPersonal.SOPORTE_PAE,
                                                      porcentaje_afectacion=D("100"), haberes=D("1000"), **base)
        self.r_beto1 = LiquidacionNomina.objects.create(persona=self.beto, asignacion=AsignacionPersonal.SOPORTE_PAE,
                                                        porcentaje_afectacion=D("60"), haberes=D("500"), **base)
        self.r_beto2 = LiquidacionNomina.objects.create(persona=self.beto, asignacion=AsignacionPersonal.POOL,
                                                        porcentaje_afectacion=D("40"), haberes=D("500"), **base)

    def usuario(self, *roles):
        u = User.objects.create_user("u" + "".join(roles), password="x", is_staff=True)
        u.groups.set(Group.objects.filter(name__in=roles))
        self.client.force_login(u)
        return u

    def datos_grilla(self):
        """Arma el POST tal como lo manda el navegador con la grilla sin tocar."""
        r = self.client.get("/nomina/2026-8/")
        self.assertEqual(r.status_code, 200)
        fs = r.context["formset"]
        datos = {f"form-{k}": v for k, v in fs.management_form.initial.items()}
        for i, form in enumerate(fs.forms):
            if form.instance.pk is None:
                continue
            for nombre in form.fields:
                if nombre == "DELETE":
                    continue
                valor = form[nombre].value()
                if nombre == "mano_obra_directa":
                    if valor:
                        datos[f"form-{i}-{nombre}"] = "on"
                    continue
                datos[f"form-{i}-{nombre}"] = "" if valor is None else str(valor).replace(".", ",")
        return fs, datos

    def test_grilla_guarda_cambios_a_mano(self):
        u = self.usuario(CARGA_PERSONAL)
        fs, datos = self.datos_grilla()
        i = next(i for i, f in enumerate(fs.forms) if f.instance.pk == self.r_ana.pk)
        datos[f"form-{i}-honorarios"] = "1.234,56"
        datos[f"form-{i}-beneficios_adicionales"] = ""
        r = self.client.post("/nomina/2026-8/", datos)
        self.assertEqual(r.status_code, 302)
        self.r_ana.refresh_from_db()
        self.assertEqual(self.r_ana.honorarios, D("1234.56"))
        self.assertEqual(self.r_ana.beneficios_adicionales, D("0"))
        self.assertEqual(self.r_ana.modificado_por, u)
        self.assertEqual(self.r_ana.history.first().history_user, u)
        self.r_beto1.refresh_from_db()
        self.assertIsNone(self.r_beto1.modificado_por)  # los renglones sin cambios no se tocan

    def test_grilla_agrega_y_borra_renglones(self):
        self.usuario(CARGA_PERSONAL)
        fs, datos = self.datos_grilla()
        n = len([f for f in fs.forms if f.instance.pk])
        datos[f"form-{n}-persona"] = str(self.ana.pk)
        datos[f"form-{n}-asignacion"] = AsignacionPersonal.ADMINISTRACION
        datos[f"form-{n}-porcentaje_afectacion"] = ""
        datos[f"form-{n}-honorarios"] = "10"
        i = next(i for i, f in enumerate(fs.forms) if f.instance.pk == self.r_ana.pk)
        datos[f"form-{i}-DELETE"] = "on"
        r = self.client.post("/nomina/2026-8/", datos)
        self.assertEqual(r.status_code, 302)
        self.assertFalse(LiquidacionNomina.objects.filter(pk=self.r_ana.pk).exists())
        nuevo = LiquidacionNomina.objects.get(persona=self.ana, periodo=self.periodo)
        self.assertEqual((nuevo.honorarios, nuevo.porcentaje_afectacion, nuevo.mano_obra_directa), (D("10"), D("100"), False))

    def test_grilla_controla_el_100_por_ciento_con_lo_que_hay_en_pantalla(self):
        self.usuario(CARGA_PERSONAL)
        fs, datos = self.datos_grilla()
        i1 = next(i for i, f in enumerate(fs.forms) if f.instance.pk == self.r_beto1.pk)
        i2 = next(i for i, f in enumerate(fs.forms) if f.instance.pk == self.r_beto2.pk)
        datos[f"form-{i1}-porcentaje_afectacion"] = "40"
        datos[f"form-{i2}-porcentaje_afectacion"] = "60"
        self.assertEqual(self.client.post("/nomina/2026-8/", datos).status_code, 302)
        self.r_beto2.refresh_from_db()
        self.assertEqual(self.r_beto2.porcentaje_afectacion, D("60"))
        fs, datos = self.datos_grilla()
        datos[f"form-{i1}-porcentaje_afectacion"] = "50"
        r = self.client.post("/nomina/2026-8/", datos)
        self.assertEqual(r.status_code, 200)
        self.assertIn("110,00%", str(r.content.decode()).replace("110.00", "110,00"))

    def test_grilla_con_error_no_guarda_nada(self):
        self.usuario(CARGA_PERSONAL)
        fs, datos = self.datos_grilla()
        i = next(i for i, f in enumerate(fs.forms) if f.instance.pk == self.r_ana.pk)
        datos[f"form-{i}-honorarios"] = "abc"
        r = self.client.post("/nomina/2026-8/", datos)
        self.assertEqual(r.status_code, 200)
        self.r_ana.refresh_from_db()
        self.assertEqual(self.r_ana.honorarios, D("0"))

    def test_solo_lectura_no_puede_guardar_y_mes_cerrado(self):
        self.usuario(SOLO_LECTURA)
        self.assertEqual(self.client.get("/nomina/2026-8/").status_code, 200)
        self.assertEqual(self.client.post("/nomina/2026-8/", {}).status_code, 403)
        self.usuario(CARGA_PERSONAL)
        self.periodo.cerrado = True
        self.periodo.save()
        self.assertEqual(self.client.post("/nomina/2026-8/", {}).status_code, 403)

    def documento(self, tipo):
        doc = DocumentoNomina(periodo=self.periodo, tipo=tipo)
        doc.archivo.save("x.pdf", ContentFile(b"%PDF"), save=True)
        return doc

    def test_reparto_por_persona_y_aplicar(self):
        u = self.usuario(CARGA_PERSONAL)
        self.documento(DocumentoNomina.Tipo.F931)
        self.documento(DocumentoNomina.Tipo.F931)  # p. ej. Valpob + Global: se suman

        def leer(doc, texto=None):
            lectura = lectores.Lectura()
            lectura.importes["27111111111"] = D("100")
            lectura.importes["20222222222"] = D("50.25")
            lectura.importes["20999999999"] = D("7")
            lectura.nombres["20999999999"] = "Sin Renglón"
            return lectura

        with mock.patch.object(docs, "leer_documento", side_effect=leer):
            prop = docs.propuesta(self.periodo, "contribuciones")
            self.assertEqual(len(prop.con_cambios), 2)
            self.assertEqual(prop.sin_renglon, [("20999999999", "Sin Renglón", D("14"))])
            self.assertEqual(self.client.get("/nomina/2026-8/documentos/contribuciones/").status_code, 200)
            self.client.post("/nomina/2026-8/documentos/contribuciones/")  # sin personas marcadas no cambia nada
            self.r_ana.refresh_from_db()
            self.assertEqual(self.r_ana.contribuciones_patronales, D("0"))
            r = self.client.post("/nomina/2026-8/documentos/contribuciones/",
                                 {"persona": [self.ana.pk, self.beto.pk]})
        self.assertEqual(r.status_code, 302)
        self.r_ana.refresh_from_db()
        self.assertEqual(self.r_ana.contribuciones_patronales, D("200"))
        self.assertEqual(self.r_ana.modificado_por, u)
        self.assertIn("F.931", self.r_ana.observaciones)
        for r in (self.r_beto1, self.r_beto2):  # quien trabaja en dos servicios lleva el total en cada renglón
            r.refresh_from_db()
            self.assertEqual(r.contribuciones_patronales, D("100.50"))
        self.assertFalse(DocumentoNomina.objects.filter(aplicado_en__isnull=True).exists())

    def test_aplicar_solo_a_las_personas_marcadas(self):
        u = self.usuario(CARGA_PERSONAL)
        self.documento(DocumentoNomina.Tipo.F931)

        def leer(doc, texto=None):
            lectura = lectores.Lectura()
            lectura.importes["27111111111"] = D("100")
            lectura.importes["20222222222"] = D("50")
            return lectura

        with mock.patch.object(docs, "leer_documento", side_effect=leer):
            self.client.post("/nomina/2026-8/documentos/contribuciones/", {"persona": [self.beto.pk]})
        self.r_ana.refresh_from_db()
        self.r_beto1.refresh_from_db()
        self.assertEqual((self.r_ana.contribuciones_patronales, self.r_beto1.contribuciones_patronales), (D("0"), D("50")))

    def test_haberes_usa_recibos_si_tambien_hay_libro(self):
        self.usuario(CARGA_PERSONAL)
        self.documento(DocumentoNomina.Tipo.RECIBOS)
        self.documento(DocumentoNomina.Tipo.LSD)

        def leer(doc, texto=None):
            lectura = lectores.Lectura()
            importe = D("2000") if doc.tipo == DocumentoNomina.Tipo.RECIBOS else D("9999")
            lectura.importes["27111111111"] = importe
            lectura.del_mes["27111111111"] = D("800")
            return lectura

        with mock.patch.object(docs, "leer_documento", side_effect=leer):
            cambiadas, prop = docs.aplicar(self.periodo, "haberes", User.objects.first())
        self.assertEqual(cambiadas, 1)
        self.assertTrue(prop.avisos)
        self.r_ana.refresh_from_db()
        self.assertEqual((self.r_ana.haberes, self.r_ana.haberes_pagados_en_el_mes), (D("2000"), D("800")))

    def test_diferencias_de_centavos_no_son_cambios(self):
        fila = docs.FilaPropuesta(persona=self.ana, cuil="1", actual=D("1000"), nuevo=D("1000.40"))
        self.assertFalse(fila.cambia)
        fila.nuevo = D("1001")
        self.assertTrue(fila.cambia)


class LectoresTest(TestCase):
    def test_importes_argentinos(self):
        self.assertEqual(lectores._ar("1.234.567,89"), D("1234567.89"))
        self.assertEqual(lectores._ar("-50,10"), D("-50.10"))


RECIBO = """
          GROUP VALPOB S.R.L.
|CC Lega. Apellido y Nombre             T   Documento    Ingreso   C.U.I.L.  |
|01   079 PRUEBA, ANA                   DU    11.111.111 21/10/24 27111111111|
|Fec.Pago Lugar de Pago                 Periodo Abonado                      |
|18/08/26 NEUQUEN                       1er.QUINCENA DE AGOSTO DE 2026       |
|Cto|Descripcion              | Unidades| Valor Unit.|   Haberes  |Apor/Contr|
|002|HORAS NORMALES           |     80.0|     3095.07|   247605.60|          |
|016|AUSENCIA HORAS           |      8.0|    -2847.61|    -1000.00|          |
|021|HORAS VIAJE              |     16.0|     5578.43|    89254.88|          |
|233|VIANDAS 545/08           |     10.0|    13095.67|   130956.69|          |
|241|JUBILACION 11 %          |         |            |            |  80133.56|
                                                 SubT    466817.17  80133.56
"""

LIBRO = """079
27-11111111-1
PRUEBA, ANA
024 - Personal de la construcción Ley N°22250
0545/08 - UOCRA -UNION OBRERA DE LA CONSTRUCCIÒN
7129 - Oficiales y operarios de la construcción (obra gruesa
002 - HORAS NORMALES
80,00
$
247.605,60
0,00
0,00 016 - AUSENCIA HORAS
8,00
$
-1.000,00
0,00
0,00
021 - HORA VIAJE
22,00
$
122.725,46
0,00
0,00 233 - VIANDAS
S/545/08
10,00
$
0,00
130.956,69
0,00
241 - JUBILACION 11 %
0,00
$
0,00
0,00
-69.886,52
Total Imp. Remunerados: 
369.331,06
Total Imp. No Remunerados: 130.956,69
Total Deducciones: 
"""


class CruceRecibosLibroTest(TestCase):
    def setUp(self):
        self.periodo = Periodo.objects.create(anio=2026, mes=8)

    def test_lectores_separan_conceptos(self):
        r = lectores.leer_recibos(RECIBO)
        self.assertEqual(r.importes["27111111111"], D("466817.17"))
        self.assertEqual(r.del_mes["27111111111"], D("466817.17"))
        self.assertEqual(r.conceptos["27111111111"]["016"][1], D("-1000.00"))
        self.assertNotIn("241", r.conceptos["27111111111"])
        # Con el mes liquidado, cuenta la fecha de pago del recibo (18/08/26).
        self.assertEqual(lectores.leer_recibos(RECIBO, 2026, 8).del_mes["27111111111"], D("466817.17"))
        self.assertEqual(lectores.leer_recibos(RECIBO, 2026, 7).del_mes.get("27111111111", D("0")), D("0"))
        l = lectores.leer_lsd(LIBRO, primera_quincena=True)
        self.assertEqual(l.importes["27111111111"], D("500287.75"))
        self.assertEqual(sum(v for _, v in l.conceptos["27111111111"].values()), D("500287.75"))
        self.assertEqual(l.conceptos["27111111111"]["233"][0], "VIANDAS S/545/08")
        self.assertEqual(sorted(l.conceptos["27111111111"]), ["002", "016", "021", "233"])

    @override_settings(MEDIA_ROOT=MEDIA)
    def test_cruce_muestra_diferencias_por_concepto(self):
        for tipo in (DocumentoNomina.Tipo.RECIBOS, DocumentoNomina.Tipo.LSD):
            doc = DocumentoNomina(periodo=self.periodo, tipo=tipo, primera_quincena=True)
            doc.archivo.save("x.pdf", ContentFile(b"%PDF"), save=True)
        with \
                mock.patch.object(docs, "leer_documento", side_effect=lambda doc, texto=None: (
                    lectores.leer_recibos(RECIBO) if doc.tipo == DocumentoNomina.Tipo.RECIBOS
                    else lectores.leer_lsd(LIBRO, primera_quincena=True))):
            cruce = docs.cruce_recibos_libro(self.periodo)
            u = User.objects.create_user("carga", password="x", is_staff=True)
            u.groups.set(Group.objects.filter(name=CARGA_PERSONAL))
            self.client.force_login(u)
            with override_settings(ALLOWED_HOSTS=["testserver"]):
                pagina = self.client.get("/nomina/2026-8/documentos/haberes/").content.decode()
                listado = self.client.get("/nomina/2026-8/documentos/").content.decode()
        self.assertIn("021 · HORA VIAJE", pagina)
        self.assertIn("no coinciden en 1 persona", listado)
        self.assertTrue(cruce.hay_diferencias)
        d = cruce.diferencias[0]
        self.assertEqual(d.diferencia, D("-33470.58"))
        self.assertEqual(d.diferencia_del_mes, D("-33470.58"))
        self.assertEqual(d.conceptos, [("021", "HORA VIAJE", D("89254.88"), D("122725.46"), D("-33470.58"))])

    def test_sin_los_dos_documentos_no_hay_cruce(self):
        self.assertIsNone(docs.cruce_recibos_libro(self.periodo))

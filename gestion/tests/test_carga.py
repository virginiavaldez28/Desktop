"""Validaciones de los formularios de carga, roles y cierre de mes."""
from datetime import date
from decimal import Decimal as D

from django.contrib.auth.models import Group, User
from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings

from gestion.calculos import calcular_mes
from gestion.catalogos import AsignacionPersonal, CategoriaCompra, ServicioCompra
from gestion.formato import moneda, porcentaje
from gestion.models import Compra, LiquidacionNomina, Periodo, Persona, Proveedor
from gestion.roles import ADMINISTRADOR, CARGA_COMPRAS, CARGA_PERSONAL, SOLO_LECTURA


class FormatoTest(TestCase):
    def test_formato_argentino(self):
        self.assertEqual(moneda(D("1234567.891")), "$ 1.234.567,89")
        self.assertEqual(moneda(D("-0.001")), "$ 0,00")
        self.assertEqual(moneda(D("-2750")), "$ -2.750,00")
        self.assertEqual(porcentaje(D("0.2872")), "28,7%")


class ValidacionesTest(TestCase):
    def setUp(self):
        self.periodo = Periodo.objects.create(anio=2026, mes=9)
        self.persona = Persona.objects.create(apellido_nombre="Pérez Juan", cuil="20111111112")

    def renglon(self, **kwargs):
        valores = dict(persona=self.persona, periodo=self.periodo, mano_obra_directa=True,
                       asignacion=AsignacionPersonal.SOPORTE_PAE, porcentaje_afectacion=D("100"))
        valores.update(kwargs)
        return LiquidacionNomina(**valores)

    def test_periodo_crea_los_9_porcentajes_manuales(self):
        self.assertEqual(self.periodo.asignaciones_manuales.count(), 9)

    def test_administracion_exige_mod_no(self):
        with self.assertRaises(ValidationError):
            self.renglon(asignacion=AsignacionPersonal.ADMINISTRACION).full_clean()
        with self.assertRaises(ValidationError):
            self.renglon(mano_obra_directa=False).full_clean()
        self.renglon(asignacion=AsignacionPersonal.ADMINISTRACION, mano_obra_directa=False).full_clean()

    def test_porcentaje_entre_0_y_100(self):
        with self.assertRaises(ValidationError):
            self.renglon(porcentaje_afectacion=D("120")).full_clean()

    def test_una_persona_no_puede_superar_100_por_ciento_en_el_mes(self):
        self.renglon(porcentaje_afectacion=D("50")).save()
        self.renglon(asignacion=AsignacionPersonal.POOL, porcentaje_afectacion=D("50")).full_clean()
        with self.assertRaises(ValidationError):
            self.renglon(asignacion=AsignacionPersonal.POOL, porcentaje_afectacion=D("60")).full_clean()

    def test_total_y_asignado(self):
        r = self.renglon(porcentaje_afectacion=D("50"), haberes=D("1000"), contribuciones_patronales=D("200"),
                         sindicato_mutual=D("50"), honorarios=D("0"))
        self.assertEqual(r.total_mes, D("1250"))
        self.assertEqual(r.asignado_servicio, D("625"))

    def test_otros_egresos_y_na_van_juntos(self):
        proveedor = Proveedor.objects.create(nombre="Estudio Contable")
        compra = Compra(fecha=date(2026, 9, 1), proveedor=proveedor, tipo_comprobante="Factura A", punto_venta=1,
                        numero=1, periodo=self.periodo, neto=D("10"),
                        categoria=CategoriaCompra.OTROS_EGRESOS, servicio_asignado=ServicioCompra.GENERAL)
        with self.assertRaises(ValidationError):
            compra.full_clean()
        compra.categoria, compra.servicio_asignado = CategoriaCompra.COMBUSTIBLE, ServicioCompra.NO_APLICA
        with self.assertRaises(ValidationError):
            compra.full_clean()
        compra.servicio_asignado = ServicioCompra.GENERAL
        compra.full_clean()

    def test_calculo_desde_la_base(self):
        self.renglon(haberes=D("1000.10")).save()
        mes = calcular_mes(self.periodo)
        self.assertEqual(mes.er.mano_obra_directa, D("1000.10"))


@override_settings(ALLOWED_HOSTS=["testserver"])
class RolesTest(TestCase):
    def usuario(self, nombre, *roles):
        u = User.objects.create_user(nombre, password="x", is_staff=True)
        u.groups.set(Group.objects.filter(name__in=roles))
        self.client.force_login(u)
        return u

    def test_roles_creados(self):
        self.assertEqual(Group.objects.filter(name__in=[ADMINISTRADOR, CARGA_COMPRAS, SOLO_LECTURA]).count(), 3)

    def test_carga_de_compras_no_ve_nomina_ni_reportes(self):
        self.usuario("compras", CARGA_COMPRAS)
        self.assertEqual(self.client.get("/admin/gestion/compra/").status_code, 200)
        self.assertEqual(self.client.get("/admin/gestion/liquidacionnomina/").status_code, 403)
        self.assertEqual(self.client.get("/reportes/estado-de-resultados/").status_code, 403)

    def test_solo_lectura_ve_reportes_pero_no_carga(self):
        self.usuario("gerencia", SOLO_LECTURA)
        Periodo.objects.create(anio=2026, mes=7)
        self.assertEqual(self.client.get("/reportes/estado-de-resultados/").status_code, 200)
        self.assertEqual(self.client.get("/admin/gestion/venta/add/").status_code, 403)

    def test_mes_cerrado_solo_lo_modifica_un_administrador(self):
        periodo = Periodo.objects.create(anio=2026, mes=7, cerrado=True)
        persona = Persona.objects.create(apellido_nombre="Pérez Juan")
        renglon = LiquidacionNomina.objects.create(
            persona=persona, periodo=periodo, asignacion=AsignacionPersonal.POOL,
        )
        url = f"/admin/gestion/liquidacionnomina/{renglon.pk}/change/"
        self.usuario("personal", CARGA_PERSONAL)
        respuesta = self.client.post(url, {"persona": persona.pk, "periodo": periodo.pk, "mano_obra_directa": "on",
                                           "asignacion": "POOL", "porcentaje_afectacion": "100", "haberes": "5",
                                           "contribuciones_patronales": "0", "sindicato_mutual": "0", "honorarios": "0"})
        self.assertEqual(respuesta.status_code, 403)
        renglon.refresh_from_db()
        self.assertEqual(renglon.haberes, 0)

    def test_carga_con_formato_argentino_y_auditoria(self):
        usuario = self.usuario("personal", CARGA_PERSONAL)
        periodo = Periodo.objects.create(anio=2026, mes=9)
        persona = Persona.objects.create(apellido_nombre="Pérez Juan")
        respuesta = self.client.post("/admin/gestion/liquidacionnomina/add/", {
            "persona": persona.pk, "periodo": periodo.pk, "mano_obra_directa": "on", "asignacion": "PAE",
            "porcentaje_afectacion": "100", "haberes": "1.234.567,89", "contribuciones_patronales": "0",
            "sindicato_mutual": "0", "honorarios": "0",
        })
        self.assertEqual(respuesta.status_code, 302, respuesta.content[:2000])
        renglon = LiquidacionNomina.objects.get()
        self.assertEqual(renglon.haberes, D("1234567.89"))
        self.assertEqual(renglon.creado_por, usuario)
        self.assertEqual(renglon.history.first().history_user, usuario)

    def test_reportes_y_exportaciones_responden(self):
        self.usuario("admin", ADMINISTRADOR)
        Periodo.objects.create(anio=2026, mes=7)
        Periodo.objects.create(anio=2026, mes=8)
        for nombre in ("estado-de-resultados", "apertura", "costos-por-servicio", "punto-de-equilibrio", "rentabilidad"):
            for extra in ("", "&formato=xlsx", "&formato=pdf"):
                respuesta = self.client.get(f"/reportes/{nombre}/?desde=2026-07&hasta=2026-08{extra}")
                self.assertEqual(respuesta.status_code, 200, (nombre, extra))
        respuesta = self.client.get("/reportes/estado-de-resultados/?comparar=1&desde=2026-07&hasta=2026-07"
                                    "&desde_b=2026-08&hasta_b=2026-08")
        self.assertContains(respuesta, "Variación")


class IvaVentasTest(TestCase):
    def test_neto_e_iva_desde_el_listado_de_facturacion(self):
        from gestion.catalogos import Servicio
        from gestion.models import Cliente, Venta
        from gestion.ventas_origen import Comprobante, completar

        periodo = Periodo.objects.create(anio=2026, mes=8)
        cliente = Cliente.objects.create(nombre="Ministerio")
        # Factura B cargada con el IVA incluido, como estaba en el Excel.
        Venta.objects.create(fecha=date(2026, 8, 1), cliente=cliente, tipo_comprobante="Factura B", punto_venta=3,
                             numero=22, periodo=periodo, servicio=Servicio.OBRAS_CIVILES, neto=D("1428830.92"))
        resultado = completar([Comprobante("Factura B", 3, 22, "Ministerio", D("1180852.00"), D("247978.92"))])
        venta = Venta.objects.get()
        self.assertEqual((venta.neto, venta.iva, venta.total), (D("1180852.00"), D("247978.92"), D("1428830.92")))
        self.assertEqual(len(resultado.neto_corregido), 1)
        # La rentabilidad usa el neto; el IVA queda como memo.
        mes = calcular_mes(periodo)
        self.assertEqual(mes.er.total_ventas, D("1180852.00"))
        self.assertEqual(mes.er.iva_ventas, D("247978.92"))

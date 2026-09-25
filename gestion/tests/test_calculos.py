"""Reglas de negocio del motor de cálculo, con números chicos y fáciles de seguir a mano."""
from decimal import Decimal as D

from django.test import SimpleTestCase

from gestion.calculos import DatosMes, costos_por_servicio, estado_resultados, punto_equilibrio, ranking
from gestion.catalogos import (
    AsignacionPersonal,
    CategoriaCompra,
    ModoAsignacion,
    RubroGasto,
    Servicio,
    ServicioCompra,
)

S = Servicio


def datos_base():
    """Ventas: PAE 600, Hidrolavadoras 300, Cercos 100 → total 1.000."""
    datos = DatosMes()
    datos.ventas[S.SOPORTE_PAE] = D("600")
    datos.ventas[S.HIDROLAVADORAS] = D("300")
    datos.ventas[S.CERCOS] = D("100")
    return datos


class PorcentajeAsignacionTest(SimpleTestCase):
    def test_automatico_es_la_participacion_en_ventas(self):
        cxs = costos_por_servicio(datos_base())
        self.assertEqual(cxs.porcentaje_asignacion[S.SOPORTE_PAE], D("0.6"))
        self.assertEqual(cxs.porcentaje_asignacion[S.HIDROLAVADORAS], D("0.3"))
        self.assertEqual(cxs.porcentaje_asignacion[S.METALURGICA], 0)

    def test_manual_reemplaza_al_automatico(self):
        datos = datos_base()
        datos.modo_asignacion = ModoAsignacion.MANUAL
        datos.asignacion_manual[S.SOPORTE_PAE] = D("50")
        datos.asignacion_manual[S.METALURGICA] = D("50")
        datos.gastos[RubroGasto.ALQUILERES] = D("200")
        cxs = costos_por_servicio(datos)
        self.assertEqual(cxs.porcentaje_asignacion[S.SOPORTE_PAE], D("0.5"))
        self.assertEqual(cxs.costos_fijos_asignados[S.METALURGICA], D("100"))
        self.assertEqual(cxs.costos_fijos_asignados[S.HIDROLAVADORAS], 0)
        self.assertEqual(cxs.advertencias, [])

    def test_manual_que_no_suma_100_avisa(self):
        datos = datos_base()
        datos.modo_asignacion = ModoAsignacion.MANUAL
        datos.asignacion_manual[S.SOPORTE_PAE] = D("40")
        self.assertTrue(costos_por_servicio(datos).advertencias)


class ComprasTest(SimpleTestCase):
    def test_regla_1_general_se_prorratea_por_ventas(self):
        datos = datos_base()
        datos.compras[(CategoriaCompra.COMBUSTIBLE.value, ServicioCompra.GENERAL.value)] = D("1000")
        datos.compras[(CategoriaCompra.COMBUSTIBLE.value, S.CERCOS.value)] = D("50")
        cxs = costos_por_servicio(datos)
        combustible = cxs.costos_variables[CategoriaCompra.COMBUSTIBLE]
        self.assertEqual(combustible[S.SOPORTE_PAE], D("600"))
        self.assertEqual(combustible[S.HIDROLAVADORAS], D("300"))
        self.assertEqual(combustible[S.CERCOS], D("150"))  # 50 directo + 100 prorrateado
        self.assertEqual(cxs.total_fila(CategoriaCompra.COMBUSTIBLE), D("1050"))
        self.assertEqual(estado_resultados(datos).combustible, D("1050"))

    def test_regla_2_otros_egresos_va_a_gastos_operativos_y_no_a_costos_por_servicio(self):
        datos = datos_base()
        datos.compras[(CategoriaCompra.OTROS_EGRESOS.value, ServicioCompra.NO_APLICA.value)] = D("120")
        datos.gastos[RubroGasto.OTROS_GASTOS_OPERATIVOS] = D("35")
        er = estado_resultados(datos)
        self.assertEqual(er.gastos_operativos[RubroGasto.OTROS_GASTOS_OPERATIVOS], D("155"))
        self.assertEqual(er.total_costo_servicios, 0)
        cxs = costos_por_servicio(datos, er)
        self.assertEqual(cxs.total_cv, 0)
        # Como gasto operativo, sí forma parte de los costos fijos que se reparten.
        self.assertEqual(cxs.costos_fijos, D("155"))


class ManoDeObraTest(SimpleTestCase):
    def test_regla_4_cuadrillas_fijas_pool_y_administracion(self):
        datos = datos_base()
        datos.ventas[S.METALURGICA] = D("100")  # ventas pool: Hidro 300 + Metal 100 = 400
        datos.mano_obra[AsignacionPersonal.SOPORTE_PAE.value] = D("500")
        datos.mano_obra[AsignacionPersonal.CERCOS.value] = D("70")
        datos.mano_obra[AsignacionPersonal.POOL.value] = D("400")
        datos.sueldos_administracion = D("220")
        er = estado_resultados(datos)
        self.assertEqual(er.mano_obra_directa, D("970"))
        self.assertEqual(er.sueldos_administracion, D("220"))

        cxs = costos_por_servicio(datos, er)
        mo = cxs.costos_variables["mano_obra"]
        self.assertEqual(mo[S.SOPORTE_PAE], D("500"))
        self.assertEqual(mo[S.CERCOS], D("70"))
        self.assertEqual(mo[S.HIDROLAVADORAS], D("300"))  # 400 × 300/400
        self.assertEqual(mo[S.METALURGICA], D("100"))
        # Administración no es costo variable: entra por costos fijos, repartida con el % de asignación.
        self.assertEqual(cxs.costos_fijos, D("220"))
        self.assertEqual(cxs.costos_fijos_asignados[S.SOPORTE_PAE], D("220") * D("600") / D("1100"))

    def test_personal_asignado_directo_a_un_servicio_del_pool_se_suma_a_ese_servicio(self):
        datos = datos_base()
        datos.mano_obra[AsignacionPersonal.HIDROLAVADORAS.value] = D("80")
        datos.mano_obra[AsignacionPersonal.POOL.value] = D("30")
        cxs = costos_por_servicio(datos)
        self.assertEqual(cxs.costos_variables["mano_obra"][S.HIDROLAVADORAS], D("110"))

    def test_pool_sin_ventas_en_el_pool_avisa(self):
        datos = DatosMes()
        datos.ventas[S.SOPORTE_PAE] = D("100")
        datos.mano_obra[AsignacionPersonal.POOL.value] = D("50")
        self.assertTrue(costos_por_servicio(datos).advertencias)


class CierreTest(SimpleTestCase):
    def test_resultado_por_servicio_cierra_con_el_resultado_operativo(self):
        datos = datos_base()
        datos.ventas[S.OBRAS_CIVILES] = D("250")
        datos.mano_obra[AsignacionPersonal.SOPORTE_PAE.value] = D("210")
        datos.mano_obra[AsignacionPersonal.OBRAS_CIVILES.value] = D("40")
        datos.mano_obra[AsignacionPersonal.POOL.value] = D("90")
        datos.sueldos_administracion = D("60")
        datos.compras[(CategoriaCompra.MATERIALES.value, ServicioCompra.GENERAL.value)] = D("33")
        datos.compras[(CategoriaCompra.OTROS_EGRESOS.value, ServicioCompra.NO_APLICA.value)] = D("12")
        datos.gastos[RubroGasto.COMISIONES_BANCARIAS] = D("9")
        datos.gastos[RubroGasto.LEASING] = D("15")
        er = estado_resultados(datos)
        cxs = costos_por_servicio(datos, er)
        self.assertEqual(round(cxs.total_resultado, 10), round(er.resultado_operativo, 10))

    def test_estado_de_resultados_completo(self):
        datos = datos_base()
        datos.gastos[RubroGasto.INTERESES] = D("10")
        datos.gastos[RubroGasto.OTROS_INGRESOS] = D("5")
        datos.gastos[RubroGasto.OTROS_EGRESOS_NO_OPERATIVOS] = D("3")
        datos.gastos[RubroGasto.IMPUESTO_GANANCIAS] = D("100")
        er = estado_resultados(datos)
        self.assertEqual(er.resultado_operativo, D("990"))
        self.assertEqual(er.resultado_antes_impuestos, D("992"))
        self.assertEqual(er.resultado_neto, D("892"))


class PuntoEquilibrioTest(SimpleTestCase):
    def test_formula(self):
        datos = datos_base()
        datos.mano_obra[AsignacionPersonal.SOPORTE_PAE.value] = D("400")  # MC% = 60%
        datos.gastos[RubroGasto.ALQUILERES] = D("300")
        general, por_servicio = punto_equilibrio(costos_por_servicio(datos))
        self.assertEqual(general.mc_porcentaje, D("0.6"))
        self.assertEqual(general.punto_equilibrio, D("500"))
        self.assertEqual(general.margen_seguridad, D("0.5"))
        self.assertEqual(general.estado, "Por encima del punto de equilibrio")
        # PAE: ventas 600, CV 400 → MC% 1/3; CF asignados 180 → PE 540.
        self.assertAlmostEqual(por_servicio[S.SOPORTE_PAE].punto_equilibrio, D("540"), places=10)

    def test_sin_ventas_no_divide_por_cero(self):
        datos = DatosMes()
        datos.gastos[RubroGasto.ALQUILERES] = D("300")
        general, _ = punto_equilibrio(costos_por_servicio(datos))
        self.assertEqual(general.punto_equilibrio, 0)


class RankingTest(SimpleTestCase):
    def test_empates_comparten_puesto(self):
        self.assertEqual(ranking({"a": D("0.5"), "b": D("0.2"), "c": D("0.5"), "d": D("-1")}),
                         {"a": 1, "c": 1, "b": 3, "d": 4})

"""Verificación contra el Excel original.

El Excel tiene datos personales (sueldos, CUIL), así que no está en el
repositorio. Para correr esta prueba, indicá dónde está:

    VALPOB_EXCEL=/ruta/Valpob_Punto_Equilibrio_Rentabilidad.xlsx python manage.py test
"""
import os
import unittest

from django.test import TestCase

from gestion.excel import leer_excel
from gestion.importacion import importar
from gestion.verificacion import verificar

RUTA = os.environ.get("VALPOB_EXCEL")


@unittest.skipUnless(RUTA and os.path.exists(RUTA), "Definí VALPOB_EXCEL con la ruta del Excel original.")
class ComparacionConExcelTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        # Con los renglones de ejemplo, para reproducir exactamente lo que suma el Excel.
        importar(leer_excel(RUTA), 2026, incluir_ejemplos=True)

    def test_todas_las_celdas_coinciden(self):
        resultado = verificar(RUTA)
        detalle = "\n".join(
            f"{l.hoja} | {l.concepto} | {l.columna}: Excel {l.excel} App {l.app}" for l in resultado.diferencias
        )
        self.assertTrue(resultado.todo_coincide, detalle)
        self.assertGreater(len(resultado.lineas), 200)

    def test_resultado_por_servicio_cierra_con_el_estado_de_resultados(self):
        resultado = verificar(RUTA)
        self.assertAlmostEqual(resultado.resultado_por_servicio_app, resultado.resultado_operativo, places=6)

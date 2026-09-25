from collections import Counter

from django.core.management.base import BaseCommand

from gestion.formato import moneda
from gestion.verificacion import verificar


class Command(BaseCommand):
    help = "Compara los números calculados por la aplicación contra los del Excel original, celda por celda."

    def add_arguments(self, parser):
        parser.add_argument("archivo", help="Ruta al Excel (.xlsx).")
        parser.add_argument("--anio", type=int, default=2026)
        parser.add_argument("--detalle", action="store_true", help="Muestra también las celdas que coinciden.")

    def handle(self, *args, **opciones):
        r = verificar(opciones["archivo"], opciones["anio"])
        por_hoja = Counter(linea.hoja for linea in r.lineas)
        ok_por_hoja = Counter(linea.hoja for linea in r.lineas if linea.coincide)

        self.stdout.write(f"Comparación contra el Excel (Costos por Servicio: {r.mes_costos})\n")
        for hoja, total in por_hoja.items():
            estilo = self.style.SUCCESS if ok_por_hoja[hoja] == total else self.style.ERROR
            self.stdout.write(estilo(f"  {hoja}: {ok_por_hoja[hoja]} de {total} celdas coinciden"))

        for linea in r.lineas:
            if opciones["detalle"] or not linea.coincide:
                marca = "OK " if linea.coincide else "DIF"
                self.stdout.write(
                    f"  [{marca}] {linea.hoja} | {linea.concepto} | {linea.columna}: "
                    f"Excel {linea.excel} — App {linea.app} — Diferencia {linea.diferencia}"
                )

        self.stdout.write("\nDiferencia de criterio (Mano de Obra Directa en Costos por Servicio):")
        if r.mano_obra_directa_omitida:
            self.stdout.write(
                "  El Excel no suma en Costos por Servicio al personal asignado directo a estos servicios "
                "(sí lo suma en el Estado de Resultados). La aplicación lo suma a su servicio:"
            )
            for servicio, monto in r.mano_obra_directa_omitida.items():
                self.stdout.write(f"    {servicio.label}: {moneda(monto)}")
        else:
            self.stdout.write("  No hay personal asignado directo a servicios del pool: no hay diferencia.")
        self.stdout.write(f"  Resultado Operativo (Estado de Resultados):        {moneda(r.resultado_operativo)}")
        self.stdout.write(f"  Suma Resultado Neto por Servicio — aplicación:     {moneda(r.resultado_por_servicio_app)}")
        self.stdout.write(f"  Suma Resultado Neto por Servicio — Excel:          {moneda(r.resultado_por_servicio_excel)}")

        if r.todo_coincide:
            self.stdout.write(self.style.SUCCESS("\nTodas las celdas comparadas coinciden."))
        else:
            self.stdout.write(self.style.ERROR(f"\nHay {len(r.diferencias)} celdas que no coinciden."))

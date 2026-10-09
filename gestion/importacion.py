"""Carga inicial: pasa los datos del Excel a la base de datos."""
from collections import Counter

from django.db import transaction

from .catalogos import ModoAsignacion
from .excel import ContenidoExcel
from .models import Cliente, Compra, GastoManual, LiquidacionNomina, Periodo, Persona, Proveedor, Venta


class ErrorImportacion(Exception):
    pass


@transaction.atomic
def importar(contenido: ContenidoExcel, anio: int, usuario=None, incluir_ejemplos=False, reemplazar=False, mes_desde=1):
    """Importa el contenido del Excel para el año indicado. Devuelve un resumen (Counter).

    Los renglones de meses anteriores a `mes_desde` se ignoran (por ejemplo, la nómina
    del período Junio, que el Excel conserva sólo como referencia).
    """
    resumen = Counter()
    if mes_desde > 1:
        antes = len(contenido.nomina) + len(contenido.ventas) + len(contenido.compras) + len(contenido.gastos)
        contenido.nomina = [r for r in contenido.nomina if r.mes >= mes_desde]
        contenido.ventas = [r for r in contenido.ventas if r.mes >= mes_desde]
        contenido.compras = [r for r in contenido.compras if r.mes >= mes_desde]
        contenido.gastos = [g for g in contenido.gastos if g.mes >= mes_desde]
        contenido.saldo_proveedores = {m: v for m, v in contenido.saldo_proveedores.items() if m >= mes_desde}
        resumen["renglones de meses anteriores omitidos"] = antes - (
            len(contenido.nomina) + len(contenido.ventas) + len(contenido.compras) + len(contenido.gastos))
    auditoria = {"creado_por": usuario, "modificado_por": usuario}

    primer_mes_con_ventas = min((r.mes for r in contenido.ventas), default=1)
    periodos = {}
    for mes in contenido.meses:
        periodo, creado = Periodo.objects.get_or_create(anio=anio, mes=mes, defaults=auditoria)
        periodos[mes] = periodo
        resumen["meses creados"] += creado
        tiene_datos = any(
            qs.filter(periodo=periodo).exists()
            for qs in (LiquidacionNomina.objects, Venta.objects, Compra.objects, GastoManual.objects)
        )
        if tiene_datos and not reemplazar:
            raise ErrorImportacion(
                f"{periodo} ya tiene datos cargados. Usá --reemplazar para borrarlos y volver a importar."
            )
        if tiene_datos:
            for modelo in (LiquidacionNomina, Venta, Compra, GastoManual):
                modelo.objects.filter(periodo=periodo).delete()
        periodo.solo_flujo = mes < primer_mes_con_ventas
        periodo.modo_asignacion = (
            ModoAsignacion.MANUAL if contenido.modo_asignacion_manual else ModoAsignacion.AUTOMATICO
        )
        if mes in contenido.saldo_proveedores:
            periodo.saldo_proveedores = contenido.saldo_proveedores[mes]
        periodo.save()

    # Personas: se identifican por CUIL; las que no tienen CUIL, por nombre.
    personas = {}
    for r in contenido.nomina:
        clave = r.cuil or r.apellido_nombre
        if clave in personas:
            continue
        if r.cuil:
            persona, creada = Persona.objects.get_or_create(
                cuil=r.cuil, defaults={"apellido_nombre": r.apellido_nombre, **auditoria},
            )
        else:
            persona, creada = Persona.objects.get_or_create(
                cuil="", apellido_nombre=r.apellido_nombre, defaults=auditoria,
            )
        personas[clave] = persona
        resumen["personas creadas"] += creada

    LiquidacionNomina.objects.bulk_create([
        LiquidacionNomina(
            persona=personas[r.cuil or r.apellido_nombre],
            periodo=periodos[r.mes],
            mano_obra_directa=r.mano_obra_directa,
            asignacion=r.asignacion,
            porcentaje_afectacion=r.porcentaje,
            regimen=r.regimen,
            haberes=r.haberes,
            contribuciones_patronales=r.contribuciones,
            sindicato_mutual=r.sindicato,
            honorarios=r.honorarios,
            haberes_pagados_en_el_mes=r.pagado_en_el_mes,
            pagos_transferencia=r.transferencias,
            beneficios_adicionales=r.beneficios,
            observaciones=r.observaciones,
            **auditoria,
        )
        for r in contenido.nomina
    ])
    resumen["renglones de nómina"] = len(contenido.nomina)

    clientes = {}
    for r in contenido.ventas:
        if r.tercero not in clientes:
            clientes[r.tercero], creado = Cliente.objects.get_or_create(nombre=r.tercero, defaults=auditoria)
            resumen["clientes creados"] += creado
    Venta.objects.bulk_create([
        Venta(
            fecha=r.fecha, cliente=clientes[r.tercero], tipo_comprobante=r.tipo_comprobante,
            punto_venta=r.punto_venta, numero=r.numero, periodo=periodos[r.mes], servicio=r.servicio,
            neto=r.monto, observaciones=r.observaciones, **auditoria,
        )
        for r in contenido.ventas
    ])
    resumen["facturas de venta"] = len(contenido.ventas)

    compras = [r for r in contenido.compras if incluir_ejemplos or not r.ejemplo]
    resumen["facturas de compra de ejemplo omitidas"] = len(contenido.compras) - len(compras)
    proveedores = {}
    for r in compras:
        if r.tercero not in proveedores:
            proveedores[r.tercero], creado = Proveedor.objects.get_or_create(nombre=r.tercero, defaults=auditoria)
            resumen["proveedores creados"] += creado
    Compra.objects.bulk_create([
        Compra(
            fecha=r.fecha, proveedor=proveedores[r.tercero], tipo_comprobante=r.tipo_comprobante,
            punto_venta=r.punto_venta, numero=r.numero, periodo=periodos[r.mes], categoria=r.categoria,
            servicio_asignado=r.servicio_asignado, neto=r.monto, observaciones=r.observaciones, **auditoria,
        )
        for r in compras
    ])
    resumen["facturas de compra"] = len(compras)

    gastos = [g for g in contenido.gastos if incluir_ejemplos or not g.ejemplo]
    resumen["gastos de ejemplo omitidos"] = len(contenido.gastos) - len(gastos)
    GastoManual.objects.bulk_create([
        GastoManual(
            periodo=periodos[g.mes], rubro=g.rubro, concepto=g.concepto, monto=g.monto,
            observaciones=g.observaciones, **auditoria,
        )
        for g in gastos
    ])
    resumen["gastos cargados a mano"] = len(gastos)
    return resumen

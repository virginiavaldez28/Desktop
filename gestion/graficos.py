"""Gráficos simples en SVG, generados en el servidor (no dependen de internet).

Los colores salen de variables CSS (--serie-1, --serie-2, …) definidas en
`static/gestion/estilos.css`, que cambian para el modo oscuro.
"""
from decimal import Decimal

from django.utils.html import escape
from django.utils.safestring import mark_safe

from .formato import moneda, numero, porcentaje


def _abreviado(valor):
    """$ 406,5 M — para ejes y etiquetas cortas."""
    valor = Decimal(valor)
    if abs(valor) >= 1_000_000:
        return f"$ {numero(valor / 1_000_000, 1)} M"
    if abs(valor) >= 1_000:
        return f"$ {numero(valor / 1_000, 0)} mil"
    return moneda(valor, 0)


def _escala_linda(minimo, maximo, marcas=5):
    """Límites y paso "redondos" para el eje."""
    minimo, maximo = min(Decimal(0), minimo), max(Decimal(0), maximo)
    rango = (maximo - minimo) or Decimal(1)
    paso_crudo = rango / marcas
    magnitud = Decimal(10) ** (len(str(int(paso_crudo))) - 1) if paso_crudo >= 1 else Decimal("0.1")
    for factor in (1, 2, 2.5, 5, 10):
        paso = magnitud * Decimal(str(factor))
        if paso >= paso_crudo:
            break
    desde = (minimo / paso).to_integral_value(rounding="ROUND_FLOOR") * paso
    hasta = (maximo / paso).to_integral_value(rounding="ROUND_CEILING") * paso
    if hasta == desde:  # todos los valores en cero
        hasta = desde + paso
    return desde, hasta, paso


def _barra(x, y0, y1, ancho, radio=4):
    """Barra vertical con las puntas de datos redondeadas y la base recta sobre el eje."""
    arriba, abajo = min(y0, y1), max(y0, y1)
    alto = abajo - arriba
    if alto < 0.5:
        return ""
    r = min(radio, ancho / 2, alto)
    if y1 < y0:  # valor positivo: redondea arriba
        return (f"M{x:.1f},{abajo:.1f} V{arriba + r:.1f} Q{x:.1f},{arriba:.1f} {x + r:.1f},{arriba:.1f} "
                f"H{x + ancho - r:.1f} Q{x + ancho:.1f},{arriba:.1f} {x + ancho:.1f},{arriba + r:.1f} V{abajo:.1f} Z")
    return (f"M{x:.1f},{arriba:.1f} V{abajo - r:.1f} Q{x:.1f},{abajo:.1f} {x + r:.1f},{abajo:.1f} "
            f"H{x + ancho - r:.1f} Q{x + ancho:.1f},{abajo:.1f} {x + ancho:.1f},{abajo - r:.1f} V{arriba:.1f} Z")


def barras_por_mes(meses, series, titulo):
    """Barras agrupadas por mes (un solo eje en pesos)."""
    ancho, alto = 760, 300
    izq, der, arriba, abajo = 78, 12, 16, 34
    valores = [v for _, vs in series for v in vs]
    desde, hasta, paso = _escala_linda(min(valores), max(valores))
    escala = (alto - arriba - abajo) / float(hasta - desde)

    def y(valor):
        return arriba + float(hasta - Decimal(valor)) * escala

    partes = [f'<svg viewBox="0 0 {ancho} {alto}" role="img" aria-label="{escape(titulo)}" class="grafico">']
    marca = desde
    while marca <= hasta:
        yy = y(marca)
        clase = "eje-cero" if marca == 0 else "grilla"
        partes.append(f'<line x1="{izq}" x2="{ancho - der}" y1="{yy:.1f}" y2="{yy:.1f}" class="{clase}"/>')
        partes.append(f'<text x="{izq - 8}" y="{yy + 4:.1f}" class="eje-texto" text-anchor="end">{escape(_abreviado(marca))}</text>')
        marca += paso

    grupo = (ancho - izq - der) / len(meses)
    ancho_barra = min(34, (grupo - 16 - 2 * (len(series) - 1)) / len(series))
    for i, mes in enumerate(meses):
        inicio = izq + i * grupo + (grupo - (ancho_barra * len(series) + 2 * (len(series) - 1))) / 2
        for j, (nombre, vs) in enumerate(series):
            x = inicio + j * (ancho_barra + 2)
            camino = _barra(x, y(0), y(vs[i]), ancho_barra)
            if camino:
                partes.append(
                    f'<path d="{camino}" class="serie-{j + 1}"><title>{escape(mes)} — {escape(nombre)}: '
                    f'{escape(moneda(vs[i]))}</title></path>'
                )
            # Zona de hover más grande que la barra.
            partes.append(
                f'<rect x="{x - 1:.1f}" y="{arriba}" width="{ancho_barra + 2:.1f}" height="{alto - arriba - abajo}" '
                f'class="zona-hover"><title>{escape(mes)} — {escape(nombre)}: {escape(moneda(vs[i]))}</title></rect>'
            )
        partes.append(
            f'<text x="{izq + i * grupo + grupo / 2:.1f}" y="{alto - 12}" class="eje-texto" text-anchor="middle">{escape(mes)}</text>'
        )
    partes.append("</svg>")
    leyenda = "".join(
        f'<span class="leyenda-item"><span class="leyenda-marca serie-{j + 1}"></span>{escape(nombre)}</span>'
        for j, (nombre, _) in enumerate(series)
    )
    return mark_safe(f'<figure class="figura"><figcaption>{escape(titulo)}</figcaption>'
                     f'<div class="leyenda">{leyenda}</div>{"".join(partes)}</figure>')


def barras_horizontales_porcentaje(items, titulo):
    """Ranking horizontal de un % por servicio, con el valor escrito al final de cada barra."""
    ancho, alto_fila = 760, 30
    izq, der = 250, 70
    alto = alto_fila * len(items) + 16
    valores = [float(v) for _, v in items] + [0.0]
    minimo, maximo = min(valores), max(valores)
    rango = (maximo - minimo) or 1.0
    escala = (ancho - izq - der) / rango
    x0 = izq + (0 - minimo) * escala

    partes = [f'<svg viewBox="0 0 {ancho} {alto}" role="img" aria-label="{escape(titulo)}" class="grafico">']
    for i, (nombre, valor) in enumerate(items):
        yy = 8 + i * alto_fila
        x1 = x0 + float(valor) * escala
        izquierda, largo = min(x0, x1), abs(x1 - x0)
        texto_valor = escape(porcentaje(valor))
        partes.append(f'<text x="{izq - 10}" y="{yy + 19}" class="eje-texto" text-anchor="end">{escape(nombre)}</text>')
        if largo >= 0.5:
            r = min(4, largo / 2)
            partes.append(
                f'<rect x="{izquierda:.1f}" y="{yy + 5}" width="{largo:.1f}" height="18" rx="{r:.1f}" class="serie-1">'
                f'<title>{escape(nombre)}: {texto_valor}</title></rect>'
            )
        # El valor va siempre a la derecha del cero, así nunca se pisa con el nombre del servicio.
        ancla, xt = "start", (x1 if valor >= 0 else x0) + 6
        partes.append(f'<text x="{xt:.1f}" y="{yy + 19}" class="valor-texto" text-anchor="{ancla}">{texto_valor}</text>')
    partes.append(f'<line x1="{x0:.1f}" x2="{x0:.1f}" y1="4" y2="{alto - 4}" class="eje-cero"/>')
    partes.append("</svg>")
    return mark_safe(f'<figure class="figura"><figcaption>{escape(titulo)}</figcaption>{"".join(partes)}</figure>')

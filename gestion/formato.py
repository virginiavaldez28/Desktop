"""Formato argentino de números: miles con punto y decimales con coma."""
from decimal import ROUND_HALF_UP, Decimal


def _agrupar(numero: Decimal, decimales: int) -> str:
    cuantizado = numero.quantize(Decimal(1).scaleb(-decimales), rounding=ROUND_HALF_UP)
    signo = "-" if cuantizado < 0 else ""
    entero, _, fraccion = f"{abs(cuantizado):.{decimales}f}".partition(".")
    grupos = []
    while entero:
        grupos.insert(0, entero[-3:])
        entero = entero[:-3]
    texto = ".".join(grupos) or "0"
    if decimales:
        texto += "," + fraccion
    if signo and set(texto) <= set("0.,"):
        signo = ""  # evita mostrar "-0,00"
    return signo + texto


def numero(valor, decimales=2):
    if valor is None or valor == "":
        return ""
    return _agrupar(Decimal(valor), decimales)


def moneda(valor, decimales=2):
    if valor is None or valor == "":
        return ""
    return "$ " + numero(valor, decimales)


def porcentaje(valor, decimales=1):
    """Recibe una proporción (0,25) y devuelve "25,0%"."""
    if valor is None or valor == "":
        return ""
    return numero(Decimal(valor) * 100, decimales) + "%"

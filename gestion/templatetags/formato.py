from django import template

from gestion import formato

register = template.Library()


@register.filter
def moneda(valor, decimales=2):
    return formato.moneda(valor, int(decimales))


@register.filter
def porcentaje(valor, decimales=1):
    return formato.porcentaje(valor, int(decimales))

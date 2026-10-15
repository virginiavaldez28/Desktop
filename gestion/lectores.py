"""Lectura de los PDF de nómina: F.931, recibos, Libro de Sueldos Digital y planillas sindicales.

Cada lector recibe el texto del PDF y devuelve, por CUIL, los importes que le corresponden a la
empresa. Son funciones puras sobre texto, así se pueden probar sin los PDF reales (que tienen
datos personales y no están en el repositorio).
"""
import re
from collections import defaultdict
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal

CERO = Decimal("0")
CENTAVO = Decimal("0.01")


class ErrorLectura(Exception):
    pass


def texto_pdf(archivo):
    """Texto de un PDF (ruta o archivo abierto)."""
    import pymupdf

    if hasattr(archivo, "read"):
        archivo.seek(0)
        documento = pymupdf.open(stream=archivo.read(), filetype="pdf")
    else:
        documento = pymupdf.open(archivo)
    return "\n".join(pagina.get_text() for pagina in documento)


def _ar(texto):
    """'1.234.567,89' → Decimal. Acepta '$', espacios y signo."""
    t = texto.replace("$", "").replace(" ", "").strip()
    negativo = t.startswith("-") or t.endswith("-")
    t = t.strip("-")
    if not t:
        return CERO
    valor = Decimal(t.replace(".", "").replace(",", "."))
    return -valor if negativo else valor


def _r(valor):
    return valor.quantize(CENTAVO, ROUND_HALF_UP)


@dataclass
class Lectura:
    """Resultado de leer un documento: un importe por CUIL y datos de control."""

    importes: dict = field(default_factory=lambda: defaultdict(lambda: CERO))
    # Parte de `importes` que se paga dentro del mismo mes (1ª quincena), sólo para haberes.
    del_mes: dict = field(default_factory=lambda: defaultdict(lambda: CERO))
    nombres: dict = field(default_factory=dict)
    detalle: dict = field(default_factory=dict)  # texto explicativo por CUIL
    # Haberes por concepto (recibos y Libro de Sueldos): {cuil: {código: [descripción, importe]}}.
    conceptos: dict = field(default_factory=lambda: defaultdict(dict))
    resumen: str = ""


# ---------------------------------------------------------------------------
# F.931 — contribuciones patronales
# ---------------------------------------------------------------------------

def leer_f931(texto):
    """Seguridad Social + Obra Social de cada persona, más ART (alícuota y cuota fija del encabezado) y seguro de vida."""
    lineas = [l.strip() for l in texto.split("\n")]
    personas = {}
    for i, l in enumerate(lineas):
        if not (re.fullmatch(r"\d{11}", l) and l[:2] in ("20", "23", "24", "27", "30", "33") and i + 1 < len(lineas)
                and not lineas[i + 1][:1].isdigit()):
            continue
        k = next((j for j in range(i + 1, min(i + 6, len(lineas))) if re.fullmatch(r"\d{6}", lineas[j])), None)
        if k is None:
            continue
        try:
            v = [_ar(x) for x in lineas[k + 13:k + 13 + 40]]
        except Exception:
            continue
        if len(v) < 40:
            continue
        personas[l] = dict(nombre=" ".join(lineas[i + 1:k]), rem9=v[9], ss=v[20], os=v[35])
    if not personas:
        raise ErrorLectura("No encontré personas en el F.931. ¿Es el PDF completo de la DDJJ (con la nómina)?")
    plano = texto.replace("\n", " ")
    m_art = re.search(r"Remun\. con ART\s*([\d.]+,\d\d)\s*([\d.]+,\d\d)", plano)
    m_fijo = re.search(r"Cantidad de CUILES con ART\s*(\d+)\s*([\d.]+,\d\d)", plano)
    m_scvo = re.search(r"Cuiles c/S\.C\.V\.O\. - Prima\s*(\d+)\s*-\s*([\d.]+,\d\d)", plano)
    if not (m_art and m_fijo):
        raise ErrorLectura("Falta la parte de la ART: subí el F.931 completo (la DDJJ con el resumen, sección "
                           "\"VII - Ley de Riesgos de Trabajo\"), no sólo el listado de la nómina.")
    base, variable = _ar(m_art.group(1)), _ar(m_art.group(2))
    tasa = (variable / base).quantize(Decimal("0.0001"), ROUND_HALF_UP) if base else CERO
    cuiles_art = int(m_fijo.group(1)) or 1
    fijo = _r(_ar(m_fijo.group(2)) / cuiles_art)
    cuiles_scvo = int(m_scvo.group(1)) if m_scvo else 0
    scvo = _r(_ar(m_scvo.group(2)) / cuiles_scvo) if cuiles_scvo else CERO
    lectura = Lectura()
    for cuil, p in personas.items():
        art = _r(tasa * p["rem9"]) + fijo
        lectura.importes[cuil] = p["ss"] + p["os"] + art + scvo
        lectura.nombres[cuil] = p["nombre"]
        lectura.detalle[cuil] = (f"F.931: Seg. Social {p['ss']} + Obra Social {p['os']} + ART {art} "
                                 f"({tasa * 100}% + cuota fija) + seguro de vida {scvo}")
    lectura.resumen = (f"{len(personas)} personas. ART {tasa * 100}% de la remuneración + {fijo} por persona; "
                       f"seguro de vida {scvo} por persona.")
    return lectura


# ---------------------------------------------------------------------------
# Recibos de sueldo
# ---------------------------------------------------------------------------

def _sumar_conceptos(lectura, cuil, conceptos):
    """Acumula los haberes por código de concepto (los descuentos, con importe 0, no se guardan)."""
    for codigo, descripcion, importe in conceptos:
        if not importe:
            continue
        actual = lectura.conceptos[cuil].setdefault(codigo, [descripcion, CERO])
        actual[1] += importe


def _recibos_columnas(texto):
    """Recibos con columnas Remunerativo / No Remunera. / Dctos (formato de Global Group)."""
    vistos = {}
    for bloque in re.split(r"\n(?=\|(?:GROUP VALPOB S\.R\.L\.|GLOBAL GROUP S\.A\.S\.) )", "\n" + texto):
        m = re.search(r"\|\s*\d+\s+\d+\s+(\S.+?)\s+\d\s+\d+\s+\d{8}\s+(\d{11})\|", bloque)
        if not m:
            continue
        per = re.search(r"\n\|(\d{2})(\d{2})(\d{4}) .+? {2,}(\S.+?) *\|\n", bloque)
        periodo = per.group(4).strip() if per else ""
        pago = (int(per.group(3)), int(per.group(2))) if per else None
        conceptos = []
        for c in re.finditer(r"\|\s*(\d{1,3})\|(.{30})\|[^|]*\| *(-?[\d.]*)\| *(-?[\d.]*)\|", bloque):
            importe = Decimal(c.group(3) or 0) + Decimal(c.group(4) or 0)
            conceptos.append((c.group(1).zfill(3), c.group(2).strip(), importe))
        sub = re.search(r"\|Subtotales *\|[^|]*\| *([\d.]+)\| *([\d.]+)\|", bloque)
        haberes = Decimal(sub.group(1)) + Decimal(sub.group(2)) if sub else sum((c[2] for c in conceptos), CERO)
        nombre = m.group(1).replace(".", ", ", 1).strip()
        vistos[(m.group(2), periodo)] = (nombre, haberes, conceptos, pago)
    return vistos


def leer_recibos(texto, anio=None, mes=None):
    """Haberes brutos (SubT) de cada recibo.

    Con el mes liquidado (`anio`, `mes`), un recibo cuenta como pagado en el mismo mes si su fecha de pago cae
    en ese mes (1ª quincena, liquidaciones finales pagadas en el mes); sin el mes, sólo los de 1ª quincena."""
    partes = re.split(r"\n(?= *(?:GROUP VALPOB S\.R\.L\.|GLOBAL GROUP S\.A\.S\.)\n)", "\n" + texto)
    vistos = {}
    for bloque in partes:
        m = re.search(r"\|\d\d +(\d{3}) (.+?) +DU +[\d.]+ +[\d/]+ +(\d{11})\|", bloque)
        if not m:
            continue
        per = re.search(r"\n\|(\d\d)/(\d\d)/(\d\d) \S+ +(.+?) *\|\n", bloque)
        periodo = per.group(4).strip() if per else ""
        pago = (2000 + int(per.group(3)), int(per.group(2))) if per else None
        sub = re.search(r"SubT +([\d.]+) +([\d.]+)", bloque)
        if sub:
            haberes = Decimal(sub.group(1))
        else:
            haberes = sum((Decimal(c.group(1) or 0) for c in re.finditer(
                r"\|\d{3}\|.{25}\|[^|]*\|[^|]*\| *(-?[\d.]*)\| *[\d.]*\|", bloque)), CERO)
        conceptos = [(c.group(1), c.group(2).strip(), Decimal(c.group(3))) for c in re.finditer(
            r"\|(\d{3})\|(.{25})\|[^|]*\|[^|]*\| *(-?[\d.]+)\|", bloque)]
        # los recibos vienen duplicados (original y copia)
        vistos[(m.group(3), periodo)] = (m.group(2).strip(), haberes, conceptos, pago)
    if not vistos:
        vistos = _recibos_columnas(texto)
    if not vistos:
        raise ErrorLectura("No encontré recibos en el PDF.")
    lectura = Lectura()
    for (cuil, periodo), (nombre, haberes, conceptos, pago) in vistos.items():
        lectura.importes[cuil] += haberes
        _sumar_conceptos(lectura, cuil, conceptos)
        if anio and mes and pago:
            del_mes = pago == (anio, mes)
        else:
            del_mes = bool(re.search(r"1(er|ra)\.? ?QUINCENA", periodo, re.I))
        if del_mes:
            lectura.del_mes[cuil] += haberes
        lectura.nombres[cuil] = nombre
        lectura.detalle[cuil] = (lectura.detalle.get(cuil, "") + f" Recibo {periodo}: {haberes}.").strip()
    lectura.resumen = f"{len(vistos)} recibos de {len(lectura.importes)} personas."
    return lectura


# ---------------------------------------------------------------------------
# Libro de Sueldos Digital
# ---------------------------------------------------------------------------

def leer_lsd(texto, primera_quincena=False):
    """Haberes = remunerativo + no remunerativo de cada persona del Libro de Sueldos Digital."""
    lineas = texto.split("\n")
    lectura = Lectura()
    i = 0
    while i < len(lineas):
        if re.fullmatch(r"\d{2}-\d{8}-\d", lineas[i].strip()) and i > 0 and re.fullmatch(r"\d{3}", lineas[i - 1].strip()):
            cuil = lineas[i].replace("-", "").strip()
            nombre = lineas[i + 1].strip()
            j = i + 2
            bloque = []
            while j < len(lineas) and not lineas[j].startswith("Total Deducciones"):
                bloque.append(lineas[j])
                j += 1
            b = "\n".join(bloque)
            rem = re.search(r"Total Imp\. Remunerados: \n([\d.,-]+)", b)
            no_rem = re.search(r"Total Imp\. No Remunerados: ([\d.,-]+)", b)
            if rem:
                haberes = _ar(rem.group(1)) + (_ar(no_rem.group(1)) if no_rem else CERO)
                lectura.importes[cuil] += haberes
                # La descripción puede ocupar dos renglones; los renglones de la ficha (modalidad, convenio,
                # puesto: "024 - Personal de la construcción…") no se toman como conceptos.
                _sumar_conceptos(lectura, cuil, [
                    (c.group(1), " ".join(c.group(2).split()), _ar(c.group(3)) + _ar(c.group(4)))
                    for c in re.finditer(r"\b(\d{3}) - ([^\n$]+(?:\n(?!\s*[\d/]+ - )[^\n$]+)?)\n[\d.,]+\n\$\n([\d.,-]+)\n([\d.,-]+)\n[\d.,-]+", b)
                ])
                if primera_quincena:
                    lectura.del_mes[cuil] += haberes
                lectura.nombres[cuil] = nombre
                lectura.detalle[cuil] = f"Libro de Sueldos: remunerativo + no remunerativo {haberes}."
            i = j
        i += 1
    if not lectura.importes:
        raise ErrorLectura("No encontré personas en el Libro de Sueldos Digital.")
    lectura.resumen = f"{len(lectura.importes)} personas" + (" (1ª quincena)" if primera_quincena else "") + "."
    return lectura


# ---------------------------------------------------------------------------
# Sindicatos (sólo la parte a cargo de la empresa)
# ---------------------------------------------------------------------------

def _repartir_intereses(lectura, intereses, base):
    total = sum(base.values(), CERO)
    if not intereses or not total:
        return
    for cuil, b in base.items():
        parte = _r(intereses * b / total)
        lectura.importes[cuil] += parte
        lectura.detalle[cuil] += f" + intereses {parte}"


def leer_spp(texto, intereses_extra=CERO):
    """Petroleros Privados: Art. 28 + Contribución Extraordinaria; los intereses del pago se reparten por persona."""
    t = texto.replace("\n", "|")
    filas = re.findall(r"(\d{11}) ([^|]+)\|S\|S\|S\|((?:\$[\d.,]+\|){10})", t)
    if not filas:
        raise ErrorLectura("No encontré personas en la planilla de Petroleros Privados (cálculo de deuda).")
    lectura = Lectura()
    totales = {}
    for cuil, nombre, valores in filas:
        v = [_ar(x) for x in valores.strip("|").split("|")]
        mutual, art28, sindicato, res57, ce = v[5:10]
        lectura.importes[cuil] = art28 + ce
        lectura.nombres[cuil] = nombre.strip()
        lectura.detalle[cuil] = f"Petroleros Privados: Art. 28 {art28} + Contribución Extraordinaria {ce}"
        totales[cuil] = mutual + art28 + sindicato + res57 + ce
    pagado = re.search(r"TOTAL \d\d/\d{4} A PAGAR\s*\n\s*\$\s*([\d.,]+)", texto)
    intereses = CERO
    if pagado:
        intereses = max(_ar(pagado.group(1)) - sum(totales.values(), CERO), CERO)
    intereses += intereses_extra
    _repartir_intereses(lectura, intereses, totales)
    lectura.resumen = (f"{len(filas)} personas. Intereses por pago fuera de término repartidos: {intereses}."
                       if intereses else f"{len(filas)} personas, sin intereses.")
    return lectura


def leer_jerarquicos(texto, intereses_extra=CERO):
    """Petroleros Jerárquicos: cuota socio cultural + asignación Vaca Muerta + Contribución Extraordinaria."""
    filas = re.findall(r"(\d{11}) ([^\n]+)\n\d\d/\d\d/\d{4}\n((?:\$ ?[\d.,]+\n){10})", texto)
    if not filas:
        raise ErrorLectura("No encontré personas en la planilla de Petroleros Jerárquicos.")
    lectura = Lectura()
    for cuil, nombre, valores in filas:
        v = [_ar(x) for x in valores.strip().split("\n")]
        socio, vm, ce = v[7], v[8], v[9]
        lectura.importes[cuil] = socio + vm + ce  # si la planilla se repite (ajuste), queda el último valor
        lectura.nombres[cuil] = nombre.strip()
        lectura.detalle[cuil] = f"Jerárquicos: cuota socio cultural {socio} + Vaca Muerta {vm} + Contribución Extraordinaria {ce}"
    _repartir_intereses(lectura, intereses_extra, dict(lectura.importes))
    lectura.resumen = f"{len(lectura.importes)} personas."
    return lectura


def leer_uocra(texto, intereses_extra=CERO):
    """UOCRA: Fondo de Cese Laboral + FICS (2 % del fondo de cese) + IERIC 1 % + FODECO 1 %."""
    if "Contrib. IERIC" not in texto:
        raise ErrorLectura('No encontré la tabla "Contrib. IERIC / Contrib. FODECO" en la DDJJ de UOCRA.')
    lineas = [l.strip() for l in texto[texto.index("Contrib. IERIC"):].split("\n")]
    lectura = Lectura()
    i = 0
    while i < len(lineas):
        if re.fullmatch(r"\d{11}", lineas[i]) and i + 1 < len(lineas) and not lineas[i + 1][:1].isdigit():
            cuil, nombre = lineas[i], lineas[i + 1]
            numeros = []
            j = i + 2
            while j < len(lineas) and not re.fullmatch(r"\d\d/\d\d/\d{4}|\d{11}", lineas[j]):
                if re.fullmatch(r"[\d.]+,\d\d", lineas[j]):
                    numeros.append(_ar(lineas[j]))
                elif lineas[j] not in ("$", "") and not re.fullmatch(r"[\d.]+,\d\d|-", lineas[j]):
                    break
                j += 1
            # Cada fila: remuneración (o 1ª + 2ª quincena + total), Fondo de Cese, IERIC 1 % y FODECO 1 %.
            # Se busca el trío fondo de cese / IERIC / FODECO (IERIC = FODECO = 1 % del fondo de cese), así no
            # se confunde con los totales que siguen a la última persona.
            trio = next((numeros[k:k + 3] for k in range(len(numeros) - 2)
                         if numeros[k + 1] == numeros[k + 2] and abs(numeros[k] * Decimal("0.01") - numeros[k + 1]) <= 1),
                        None)
            if trio:
                fcl, ieric, fodeco = trio
                fics = _r(fcl * Decimal("0.02"))
                lectura.importes[cuil] = fcl + fics + ieric + fodeco
                lectura.nombres[cuil] = nombre
                lectura.detalle[cuil] = f"UOCRA: Fondo de Cese {fcl} + FICS {fics} + IERIC {ieric} + FODECO {fodeco}"
            i = j
            continue
        i += 1
    if not lectura.importes:
        raise ErrorLectura("No pude leer las personas de la tabla IERIC/FODECO de la DDJJ de UOCRA.")
    _repartir_intereses(lectura, intereses_extra, dict(lectura.importes))
    lectura.resumen = f"{len(lectura.importes)} personas" + (f", intereses repartidos {intereses_extra}" if intereses_extra else "") + "."
    return lectura

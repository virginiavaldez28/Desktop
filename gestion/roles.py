"""Roles de usuario (grupos de permisos).

Se crean y actualizan solos cada vez que se corre `migrate`. Para darle un rol
a alguien, en "Usuarios" se lo agrega al grupo correspondiente; una persona
puede tener más de un rol (por ejemplo "Carga de Compras" + "Solo lectura").
"""
from django.contrib.auth.models import Group, Permission

ADMINISTRADOR = "Administrador"
CARGA_PERSONAL = "Carga de Personal"
CARGA_COMPRAS = "Carga de Compras"
CARGA_VENTAS = "Carga de Ventas"
SOLO_LECTURA = "Solo lectura"

TODAS = ("add", "change", "delete", "view")
MODELOS_GESTION = (
    "periodo", "asignacionmanual", "persona", "cliente", "proveedor",
    "liquidacionnomina", "compra", "venta", "gastomanual",
)

PERMISOS_POR_ROL = {
    ADMINISTRADOR: (
        [("gestion", m, a) for m in MODELOS_GESTION for a in TODAS]
        + [("auth", m, a) for m in ("user", "group") for a in TODAS]
        + [("gestion", None, "ver_reportes")]
    ),
    CARGA_PERSONAL: (
        [("gestion", m, a) for m in ("persona", "liquidacionnomina") for a in TODAS]
        + [("gestion", "periodo", "view")]
    ),
    CARGA_COMPRAS: (
        [("gestion", m, a) for m in ("proveedor", "compra") for a in TODAS]
        + [("gestion", "periodo", "view")]
    ),
    CARGA_VENTAS: (
        [("gestion", m, a) for m in ("cliente", "venta") for a in TODAS]
        + [("gestion", "periodo", "view")]
    ),
    SOLO_LECTURA: (
        [("gestion", m, "view") for m in MODELOS_GESTION]
        + [("gestion", None, "ver_reportes")]
    ),
}


def crear_roles(**kwargs):
    for nombre, permisos in PERMISOS_POR_ROL.items():
        grupo, _ = Group.objects.get_or_create(name=nombre)
        codenames = []
        for app, modelo, accion in permisos:
            codename = accion if modelo is None else f"{accion}_{modelo}"
            codenames.append((app, codename))
        encontrados = [
            p for p in Permission.objects.select_related("content_type").filter(
                codename__in=[c for _, c in codenames]
            )
            if (p.content_type.app_label, p.codename) in codenames
        ]
        grupo.permissions.set(encontrados)


def es_administrador(usuario):
    return usuario.is_superuser or usuario.groups.filter(name=ADMINISTRADOR).exists()


def puede_ver_reportes(usuario):
    return usuario.is_active and usuario.has_perm("gestion.ver_reportes")

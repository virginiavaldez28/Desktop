from decimal import Decimal

from django.db import migrations, models


NETO = dict(
    decimal_places=2,
    max_digits=16,
    verbose_name="neto (sin IVA)",
    help_text="Importe sin IVA: es el que se usa en los reportes de rentabilidad. "
              "Las notas de crédito se cargan en negativo.",
)
IVA = dict(
    decimal_places=2,
    max_digits=16,
    default=Decimal("0"),
    verbose_name="IVA",
    help_text="IVA discriminado en la factura (0 en facturas C). En notas de crédito, en negativo.",
)


def operaciones(modelo):
    return [
        migrations.RenameField(model_name=modelo, old_name="monto", new_name="neto"),
        migrations.AlterField(model_name=modelo, name="neto", field=models.DecimalField(**NETO)),
        migrations.AddField(model_name=modelo, name="iva", field=models.DecimalField(**IVA)),
    ]


class Migration(migrations.Migration):
    """El importe de ventas y compras pasa a llamarse "neto" y se agrega el IVA.

    Los importes ya cargados eran sin IVA, así que se conservan tal cual como neto.
    """

    dependencies = [("gestion", "0003_epp_por_personal")]

    operations = (
        operaciones("compra") + operaciones("historicalcompra")
        + operaciones("venta") + operaciones("historicalventa")
    )

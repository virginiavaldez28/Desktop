from django.apps import AppConfig
from django.db.models.signals import post_migrate


class GestionConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "gestion"
    verbose_name = "Gestión Financiera"

    def ready(self):
        from .roles import crear_roles

        post_migrate.connect(crear_roles, sender=self)

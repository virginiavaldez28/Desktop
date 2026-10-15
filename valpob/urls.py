from django.contrib import admin
from django.urls import path

from gestion import nomina, views

urlpatterns = [
    path("", views.inicio, name="inicio"),
    path("reportes/<slug:nombre>/", views.reporte, name="reporte"),
    path("nomina/", nomina.nomina_ultimo_mes, name="nomina"),
    path("nomina/<int:anio>-<int:mes>/", nomina.nomina_mes, name="nomina_mes"),
    path("nomina/documentos/", nomina.documentos_ultimo_mes, name="documentos_nomina"),
    path("nomina/<int:anio>-<int:mes>/copiar/", nomina.nomina_copiar_mes, name="nomina_copiar_mes"),
    path("nomina/<int:anio>-<int:mes>/documentos/", nomina.nomina_documentos, name="nomina_documentos"),
    path("nomina/<int:anio>-<int:mes>/documentos/<slug:grupo>/", nomina.nomina_documentos_aplicar,
         name="nomina_documentos_aplicar"),
    path("nomina/documento/<int:pk>/descargar/", nomina.documento_descargar, name="documento_descargar"),
    path("nomina/documento/<int:pk>/borrar/", nomina.documento_borrar, name="documento_borrar"),
    path("admin/", admin.site.urls),
]

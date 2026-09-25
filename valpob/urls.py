from django.contrib import admin
from django.urls import path

from gestion import views

urlpatterns = [
    path("", views.inicio, name="inicio"),
    path("reportes/<slug:nombre>/", views.reporte, name="reporte"),
    path("admin/", admin.site.urls),
]

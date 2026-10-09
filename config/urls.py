from django.contrib import admin
from django.urls import include, path
from django.views.generic import RedirectView


urlpatterns = [
    path("admin/", admin.site.urls),
    path("", RedirectView.as_view(pattern_name="usuarios:dashboard", permanent=False)),
    path("usuarios/", include("usuarios.urls")),
    path("documentos/", include("documentos.urls")),
    path("firma/", include("firmas.urls")),
]

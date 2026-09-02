from django.urls import include, path
from django.views.generic import RedirectView


urlpatterns = [
    path("", RedirectView.as_view(pattern_name="usuarios:dashboard", permanent=False)),
    path("usuarios/", include("usuarios.urls")),
    path("documentos/", include("documentos.urls")),
]

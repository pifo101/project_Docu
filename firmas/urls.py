from django.urls import path

from . import view


app_name = "firmas"

urlpatterns = [
    path("perfil/guardar/", view.profile_signature_save_view, name="profile_save"),
    path("perfil/eliminar/", view.profile_signature_delete_view, name="profile_delete"),
    path("perfil/imagen/", view.profile_signature_preview_view, name="profile_preview"),
    path("destinatarios/<int:pk>/firmar/", view.recipient_sign_view, name="recipient_sign"),
    path("solicitud-demo/", view.request_view, name="request"),
    path("solicitud-demo/revisar/", view.sign_view, name="sign"),
    path("solicitud-demo/completado/", view.completed_view, name="completed"),
]

from django.urls import path

from . import view


app_name = "firmas"

urlpatterns = [
    path("solicitud-demo/", view.request_view, name="request"),
    path("solicitud-demo/revisar/", view.sign_view, name="sign"),
    path("solicitud-demo/completado/", view.completed_view, name="completed"),
]

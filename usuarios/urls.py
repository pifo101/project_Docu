from django.urls import path

from . import view


app_name = "usuarios"

urlpatterns = [
    path("login/", view.login_view, name="login"),
    path("registro/", view.register_view, name="register"),
]

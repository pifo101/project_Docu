from django.urls import path

from . import view


app_name = "usuarios"

urlpatterns = [
    path("login/", view.login_view, name="login"),
    path("registro/", view.register_view, name="register"),
    path("dashboard/", view.dashboard_view, name="dashboard"),
    path("perfil/", view.profile_view, name="profile"),
]

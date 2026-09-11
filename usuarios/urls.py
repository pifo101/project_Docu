from django.urls import path

from . import view


app_name = "usuarios"

urlpatterns = [
    path("login/", view.login_view, name="login"),
    path("registro/", view.register_view, name="register"),
    path("verificar-correo/<str:token>/", view.verify_email_view, name="verify_email"),
    path(
        "reenviar-verificacion/",
        view.resend_verification_view,
        name="resend_verification",
    ),
    path("dashboard/", view.dashboard_view, name="dashboard"),
    path("perfil/", view.profile_view, name="profile"),
    path("cerrar-sesion/", view.logout_view, name="logout"),
]

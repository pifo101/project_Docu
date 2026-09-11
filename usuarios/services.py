from datetime import timedelta

from django.conf import settings
from django.core import signing
from django.core.mail import send_mail
from django.db import transaction
from django.urls import reverse
from django.utils import timezone

from .models import Usuario


EMAIL_VERIFICATION_SALT = "usuarios.verificacion-email"


def crear_token_verificacion_email(usuario):
    return signing.dumps(
        {
            "uid": usuario.pk,
            "version": usuario.version_verificacion_email,
        },
        salt=EMAIL_VERIFICATION_SALT,
        compress=True,
    )


def enviar_correo_verificacion(usuario, request, limitar_reenvio=True):
    ahora = timezone.now()
    with transaction.atomic():
        usuario = Usuario.objects.select_for_update().get(pk=usuario.pk)
        if usuario.email_verificado:
            return False
        if (
            limitar_reenvio
            and usuario.fecha_ultimo_envio_verificacion
            and usuario.fecha_ultimo_envio_verificacion
            > ahora - timedelta(seconds=settings.EMAIL_VERIFICATION_RESEND_COOLDOWN)
        ):
            return False

        usuario.version_verificacion_email += 1
        usuario.fecha_ultimo_envio_verificacion = ahora
        usuario.save(
            update_fields=(
                "version_verificacion_email",
                "fecha_ultimo_envio_verificacion",
            )
        )
        token = crear_token_verificacion_email(usuario)
        enlace = request.build_absolute_uri(
            reverse("usuarios:verify_email", args=[token])
        )
        minutos = max(1, settings.EMAIL_VERIFICATION_TIMEOUT // 60)
        send_mail(
            subject="Verifica tu correo en ADICLA Sign",
            message=(
                "Confirma que controlas este correo para habilitar las operaciones "
                "protegidas de ADICLA Sign.\n\n"
                f"Verificar correo: {enlace}\n\n"
                f"El enlace expira en {minutos} minutos. Si no solicitaste esta cuenta, "
                "puedes ignorar este mensaje."
            ),
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[usuario.email],
            fail_silently=False,
        )
        return True


def _datos_token_email(token):
    try:
        return signing.loads(
            token,
            salt=EMAIL_VERIFICATION_SALT,
            max_age=settings.EMAIL_VERIFICATION_TIMEOUT,
        )
    except (signing.BadSignature, signing.SignatureExpired):
        return None


def token_verificacion_email_valido(token):
    datos = _datos_token_email(token)
    if not isinstance(datos, dict) or not isinstance(datos.get("uid"), int):
        return False
    return Usuario.objects.filter(
        pk=datos["uid"],
        email_verificado=False,
        version_verificacion_email=datos.get("version"),
    ).exists()


def verificar_token_email(token):
    datos = _datos_token_email(token)
    if not isinstance(datos, dict) or not isinstance(datos.get("uid"), int):
        return None

    with transaction.atomic():
        usuario = Usuario.objects.select_for_update().filter(pk=datos["uid"]).first()
        if (
            usuario is None
            or usuario.email_verificado
            or usuario.version_verificacion_email != datos.get("version")
        ):
            return None

        usuario.email_verificado = True
        usuario.fecha_verificacion_email = timezone.now()
        usuario.save(
            update_fields=("email_verificado", "fecha_verificacion_email")
        )
        return usuario

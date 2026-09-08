from django.conf import settings
from django.db import models

from documentos.models import DestinatarioDocumento


class Firma(models.Model):
    class Metodo(models.TextChoices):
        PERFIL = "PERFIL", "Firma guardada"
        DIBUJADA = "DIBUJADA", "Firma dibujada"

    # La relación uno a uno hace cumplir en base de datos una firma por destinatario.
    destinatario = models.OneToOneField(
        DestinatarioDocumento,
        on_delete=models.CASCADE,
        related_name="firma",
    )
    imagen = models.BinaryField()
    formato = models.CharField(max_length=30, default="image/png", editable=False)
    metodo = models.CharField(
        max_length=10,
        choices=Metodo.choices,
        default=Metodo.DIBUJADA,
    )
    consentimiento = models.BooleanField(default=False)
    fecha_firma = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-fecha_firma",)
        verbose_name = "firma"
        verbose_name_plural = "firmas"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(consentimiento=True),
                name="firma_requiere_consentimiento",
            )
        ]

    def __str__(self):
        return f"Firma de {self.destinatario.usuario}"


class FirmaPerfil(models.Model):
    usuario = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="firma_perfil",
    )
    imagen = models.BinaryField()
    formato = models.CharField(max_length=30, editable=False)
    fecha_creacion = models.DateTimeField(auto_now_add=True)
    fecha_actualizacion = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "firma de perfil"
        verbose_name_plural = "firmas de perfil"

    def __str__(self):
        return f"Firma guardada de {self.usuario}"

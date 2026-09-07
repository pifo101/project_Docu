from django.db import models

from documentos.models import DestinatarioDocumento


class Firma(models.Model):
    # La relación uno a uno hace cumplir en base de datos una firma por destinatario.
    destinatario = models.OneToOneField(
        DestinatarioDocumento,
        on_delete=models.CASCADE,
        related_name="firma",
    )
    imagen = models.BinaryField()
    formato = models.CharField(max_length=30, default="image/png", editable=False)
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

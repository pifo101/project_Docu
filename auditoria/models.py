from django.conf import settings
from django.db import models


class EventoAuditoria(models.Model):
    class Tipo(models.TextChoices):
        DOCUMENTO_CREADO = "DOCUMENTO_CREADO", "Documento creado"
        DOCUMENTO_ENVIADO = "DOCUMENTO_ENVIADO", "Documento enviado"
        DOCUMENTO_VISUALIZADO = "DOCUMENTO_VISUALIZADO", "Documento visualizado"
        FIRMA_COMPLETADA = "FIRMA_COMPLETADA", "Firma completada"
        DOCUMENTO_RECHAZADO = "DOCUMENTO_RECHAZADO", "Documento rechazado"
        PROCESO_FINALIZADO = "PROCESO_FINALIZADO", "Proceso finalizado"

    documento = models.ForeignKey(
        "documentos.Documento",
        on_delete=models.PROTECT,
        related_name="eventos_auditoria",
    )
    envio = models.ForeignKey(
        "documentos.EnvioDocumento",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="eventos_auditoria",
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="eventos_auditoria",
    )
    tipo = models.CharField(max_length=30, choices=Tipo.choices, db_index=True)
    fecha_hora = models.DateTimeField(auto_now_add=True, editable=False, db_index=True)
    direccion_ip = models.GenericIPAddressField(null=True, blank=True)
    informacion_adicional = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ("fecha_hora", "id")
        verbose_name = "evento de auditoría"
        verbose_name_plural = "eventos de auditoría"
        indexes = [
            models.Index(fields=("documento", "fecha_hora"), name="aud_doc_fecha_idx"),
            models.Index(fields=("envio", "fecha_hora"), name="aud_env_fecha_idx"),
        ]

    def __str__(self):
        return f"{self.get_tipo_display()} - {self.documento}"

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
        USUARIO_ORG_MODIFICADA = (
            "USUARIO_ORG_MODIFICADA",
            "Organización de usuario modificada",
        )

    documento = models.ForeignKey(
        "documentos.Documento",
        null=True,
        blank=True,
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
    usuario_afectado = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="eventos_administrativos_recibidos",
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
            models.Index(
                fields=("usuario_afectado", "fecha_hora"),
                name="aud_usuario_fecha_idx",
            ),
        ]
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(
                        documento__isnull=False,
                        usuario_afectado__isnull=True,
                    )
                    | models.Q(
                        documento__isnull=True,
                        envio__isnull=True,
                        usuario_afectado__isnull=False,
                    )
                ),
                name="auditoria_contexto_valido",
            )
        ]

    def __str__(self):
        contexto = self.documento or self.usuario_afectado
        return f"{self.get_tipo_display()} - {contexto}"

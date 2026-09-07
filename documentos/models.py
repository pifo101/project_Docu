import hashlib

from django.conf import settings
from django.core.validators import FileExtensionValidator
from django.db import models

from .validators import validar_pdf


class Documento(models.Model):
    propietario = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="documentos",
    )
    archivo = models.FileField(
        upload_to="documentos/%Y/%m/",
        validators=[FileExtensionValidator(["pdf"]), validar_pdf],
    )
    nombre_original = models.CharField(max_length=255)
    tamano = models.PositiveBigIntegerField()
    hash_sha256 = models.CharField(max_length=64, editable=False)
    fecha_creacion = models.DateTimeField(auto_now_add=True)
    fecha_actualizacion = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-fecha_creacion",)
        verbose_name = "documento"
        verbose_name_plural = "documentos"

    def __str__(self):
        return self.nombre_original

    def save(self, *args, **kwargs):
        if self.archivo:
            self.archivo.seek(0)
            contenido = self.archivo.read()
            self.tamano = len(contenido)
            self.hash_sha256 = hashlib.sha256(contenido).hexdigest()
            self.archivo.seek(0)
            if not self.nombre_original:
                self.nombre_original = self.archivo.name
        return super().save(*args, **kwargs)

from django.conf import settings
from django.core.exceptions import ValidationError


def validar_pdf(archivo):
    if not archivo or not archivo.size:
        raise ValidationError("El archivo PDF no puede estar vacío.", code="empty_pdf")

    max_size = settings.DOCUMENTO_MAX_FILE_SIZE
    if archivo.size > max_size:
        raise ValidationError(
            "El archivo excede el tamaño máximo permitido de %(max_size)s MB.",
            code="file_too_large",
            params={"max_size": max_size // (1024 * 1024)},
        )

    archivo.seek(0)
    encabezado = archivo.read(5)
    archivo.seek(0)
    if encabezado != b"%PDF-":
        raise ValidationError(
            "El contenido del archivo no corresponde a un PDF.",
            code="invalid_pdf_content",
        )

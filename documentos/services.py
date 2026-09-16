import hashlib
import threading
from io import BytesIO

from django.core.files.base import ContentFile
from django.db import IntegrityError, connection, transaction
from django.db.models import Count, Q
from django.urls import reverse
from pypdf import PdfReader, PdfWriter
from pypdf.errors import PdfReadError
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas

from auditoria.models import EventoAuditoria
from auditoria.services import registrar_evento

from .models import (
    DestinatarioDocumento,
    Documento,
    DocumentoResultado,
    EnvioDocumento,
    CampoFirma,
)


PENDING_RECIPIENT_STATES = (
    DestinatarioDocumento.Estado.PENDIENTE,
    DestinatarioDocumento.Estado.VISTO,
)

RECIPIENT_STATUS_PRESENTATION = {
    DestinatarioDocumento.Estado.BORRADOR: ("Borrador", "draft", "○"),
    DestinatarioDocumento.Estado.PENDIENTE: ("Pendiente", "pending", "○"),
    DestinatarioDocumento.Estado.VISTO: ("Visto", "viewed", "◉"),
    DestinatarioDocumento.Estado.FIRMADO: ("Firmado", "complete", "✓"),
}
FORMATOS_FIRMA_SOPORTADOS = {"image/png", "image/jpeg"}
_SQLITE_RESULT_LOCK = threading.Lock()


class ResultadoPDFError(Exception):
    pass


def envio_esta_completo(envio):
    destinatarios = envio.destinatarios.all()
    return destinatarios.exists() and not destinatarios.exclude(
        estado=DestinatarioDocumento.Estado.FIRMADO
    ).exists()


def calcular_rectangulo_pdf(campo, page_width, page_height, left=0, bottom=0):
    width = float(campo.ancho) * page_width
    height = float(campo.alto) * page_height
    x = left + float(campo.x) * page_width
    y = bottom + page_height - float(campo.y) * page_height - height
    return x, y, width, height


def calcular_colocacion_firma(rectangulo, image_width, image_height):
    x, y, field_width, field_height = rectangulo
    scale = min(field_width / image_width, field_height / image_height)
    width = image_width * scale
    height = image_height * scale
    return (
        x + (field_width - width) / 2,
        y + (field_height - height) / 2,
        width,
        height,
    )


def _cargar_destinatarios_validados(envio, page_count):
    destinatarios = list(
        envio.destinatarios.select_related("firma").prefetch_related("campos_firma")
    )
    if not destinatarios:
        raise ResultadoPDFError("El envío no tiene destinatarios.")
    if any(
        destinatario.estado != DestinatarioDocumento.Estado.FIRMADO
        for destinatario in destinatarios
    ):
        raise ResultadoPDFError("El envío todavía tiene firmas pendientes.")

    campos_por_pagina = {}
    for destinatario in destinatarios:
        campos = list(destinatario.campos_firma.all())
        campos_firma = [campo for campo in campos if campo.tipo == CampoFirma.Tipo.FIRMA]
        if not campos_firma:
            raise ResultadoPDFError("Cada destinatario debe tener al menos un campo de firma.")
        try:
            firma = destinatario.firma
        except Exception as error:
            raise ResultadoPDFError("Cada destinatario debe tener exactamente una firma.") from error
        if firma.formato not in FORMATOS_FIRMA_SOPORTADOS:
            raise ResultadoPDFError("Una firma utiliza un formato no soportado.")
        for campo in campos:
            if not 1 <= campo.pagina <= page_count:
                raise ResultadoPDFError("Un campo apunta a una página inexistente.")
            if campo.tipo != CampoFirma.Tipo.FIRMA and campo.valor is None:
                raise ResultadoPDFError("Un campo del documento no tiene un valor completado.")
            campos_por_pagina.setdefault(campo.pagina - 1, []).append(
                (campo, firma if campo.tipo == CampoFirma.Tipo.FIRMA else None)
            )
    return campos_por_pagina


def _dibujar_texto(overlay, valor, rectangulo):
    x, y, width, height = rectangulo
    font_size = max(6, min(12, height * 0.55))
    original_text = str(valor).replace("\r", " ").replace("\n", " ").strip()
    text = original_text
    while text and stringWidth(text, "Helvetica", font_size) > width - 4:
        text = text[:-1]
    if text != original_text and len(text) > 3:
        text = text[:-3] + "..."
    overlay.setFont("Helvetica", font_size)
    overlay.setFillColorRGB(0.031, 0.141, 0.435)
    overlay.drawString(x + 2, y + max(1, (height - font_size) / 2), text)


def _dibujar_checkbox(overlay, marcado, rectangulo):
    x, y, width, height = rectangulo
    size = min(width, height) * 0.62
    left = x + (width - size) / 2
    bottom = y + (height - size) / 2
    overlay.setLineWidth(max(1, size * 0.07))
    overlay.setStrokeColorRGB(0.031, 0.141, 0.435)
    overlay.rect(left, bottom, size, size, stroke=1, fill=0)
    if marcado:
        overlay.setLineWidth(max(1.3, size * 0.1))
        overlay.line(left + size * 0.2, bottom + size * 0.5, left + size * 0.43, bottom + size * 0.25)
        overlay.line(left + size * 0.43, bottom + size * 0.25, left + size * 0.82, bottom + size * 0.78)


def _crear_overlay(page, campos):
    box = page.cropbox
    page_width = float(page.mediabox.width)
    page_height = float(page.mediabox.height)
    crop_width = float(box.width)
    crop_height = float(box.height)
    left = float(box.left)
    bottom = float(box.bottom)
    output = BytesIO()
    overlay = canvas.Canvas(output, pagesize=(page_width, page_height), invariant=1)
    for campo, firma in campos:
        rectangulo = calcular_rectangulo_pdf(
            campo, crop_width, crop_height, left=left, bottom=bottom
        )
        if campo.tipo == CampoFirma.Tipo.FIRMA:
            try:
                image = ImageReader(BytesIO(bytes(firma.imagen)))
                image_width, image_height = image.getSize()
            except Exception as error:
                raise ResultadoPDFError("No se pudo leer una imagen de firma.") from error
            x, y, width, height = calcular_colocacion_firma(
                rectangulo, image_width, image_height
            )
            overlay.drawImage(
                image,
                x,
                y,
                width=width,
                height=height,
                preserveAspectRatio=True,
                mask="auto",
            )
        elif campo.tipo == CampoFirma.Tipo.CHECKBOX:
            _dibujar_checkbox(overlay, campo.valor == "true", rectangulo)
        else:
            _dibujar_texto(overlay, campo.valor, rectangulo)
    overlay.save()
    output.seek(0)
    return PdfReader(output).pages[0]


def construir_pdf_resultado(envio):
    if envio.estado != EnvioDocumento.Estado.ENVIADO:
        raise ResultadoPDFError("El envío no está en estado ENVIADO.")
    try:
        with envio.documento.archivo.open("rb") as original:
            original_bytes = original.read()
            if hashlib.sha256(original_bytes).hexdigest() != envio.documento.hash_sha256:
                raise ResultadoPDFError("El PDF original no coincide con su hash registrado.")
            reader = PdfReader(BytesIO(original_bytes))
            if reader.is_encrypted:
                raise ResultadoPDFError("El PDF original está cifrado.")
            page_count = len(reader.pages)
            if page_count < 1:
                raise ResultadoPDFError("El PDF original no contiene páginas.")
            campos_por_pagina = _cargar_destinatarios_validados(envio, page_count)
            writer = PdfWriter()
            for index, page in enumerate(reader.pages):
                if page.rotation:
                    page.transfer_rotation_to_content()
                campos = campos_por_pagina.get(index)
                if campos:
                    page.merge_page(_crear_overlay(page, campos), over=True)
                writer.add_page(page)
            output = BytesIO()
            writer.write(output)
            return output.getvalue()
    except ResultadoPDFError:
        raise
    except (OSError, PdfReadError, TypeError, ValueError) as error:
        raise ResultadoPDFError("No se pudo leer o procesar el PDF original.") from error
    except Exception as error:
        raise ResultadoPDFError("No se pudo generar el PDF resultante.") from error


def generar_resultado_si_completo(
    envio_id, actor=None, request=None, _sqlite_lock_acquired=False
):
    if connection.vendor == "sqlite" and not _sqlite_lock_acquired:
        with _SQLITE_RESULT_LOCK:
            return generar_resultado_si_completo(
                envio_id,
                actor=actor,
                request=request,
                _sqlite_lock_acquired=True,
            )
    saved_name = None
    storage = DocumentoResultado._meta.get_field("archivo").storage
    try:
        with transaction.atomic():
            envio = (
                EnvioDocumento.objects.select_for_update()
                .select_related("documento")
                .get(pk=envio_id)
            )
            existente = DocumentoResultado.objects.filter(envio=envio).first()
            if existente is not None:
                return existente
            if not envio_esta_completo(envio):
                return None

            pdf = construir_pdf_resultado(envio)
            resultado = DocumentoResultado(
                envio=envio,
                hash_sha256=hashlib.sha256(pdf).hexdigest(),
                tamano=len(pdf),
            )
            resultado.archivo.save("resultado.pdf", ContentFile(pdf), save=False)
            saved_name = resultado.archivo.name
            resultado.save(force_insert=True)
            registrar_evento(
                tipo=EventoAuditoria.Tipo.PROCESO_FINALIZADO,
                envio=envio,
                actor=actor,
                request=request,
                informacion_adicional={
                    "resultado_id": resultado.pk,
                    "cantidad_firmantes": envio.destinatarios.count(),
                },
            )
            return resultado
    except IntegrityError:
        if saved_name:
            storage.delete(saved_name)
        return DocumentoResultado.objects.get(envio_id=envio_id)
    except ResultadoPDFError:
        if saved_name:
            storage.delete(saved_name)
        raise
    except Exception as error:
        if saved_name:
            storage.delete(saved_name)
        raise ResultadoPDFError("No se pudo guardar el PDF resultante.") from error


def sender_documents_context(user):
    documents = (
        Documento.objects.filter(propietario=user)
        .select_related("envio")
        .prefetch_related("envio__destinatarios")
    )
    return {
        "owned_documents": documents,
        "owned_document_count": documents.count(),
        "sent_document_count": documents.filter(
            envio__estado=EnvioDocumento.Estado.ENVIADO,
        ).count(),
        "waiting_signature_count": DestinatarioDocumento.objects.filter(
            envio__remitente=user,
            envio__estado=EnvioDocumento.Estado.ENVIADO,
            estado__in=PENDING_RECIPIENT_STATES,
        ).count(),
        "recipient_pending_count": recipient_documents_queryset(user).filter(
            estado__in=PENDING_RECIPIENT_STATES,
        ).count(),
    }


def document_tracking_context(document):
    try:
        envio = document.envio
    except EnvioDocumento.DoesNotExist:
        envio = None

    if envio is None:
        return {
            "envio": None,
            "tracking_recipients": [],
            "signature_total": 0,
            "signature_completed": 0,
            "signature_pending": 0,
            "signature_percentage": 0,
            "all_signed": False,
            "activity_events": [],
            "last_activity": None,
            "resultado_disponible": False,
            "signed_document_download_url": None,
        }

    recipients = list(envio.destinatarios.all())
    tracking_recipients = []
    activity_events = []

    if envio.estado == EnvioDocumento.Estado.ENVIADO and envio.fecha_envio:
        activity_events.append({
            "occurred_at": envio.fecha_envio,
            "description": "Documento enviado",
            "kind": "sent",
            "order": 0,
        })

    for recipient in recipients:
        signature = getattr(recipient, "firma", None)
        label, status_class, symbol = RECIPIENT_STATUS_PRESENTATION.get(
            recipient.estado,
            (recipient.get_estado_display(), "draft", "○"),
        )
        tracking_recipients.append({
            "recipient": recipient,
            "signature": signature,
            "label": label,
            "status_class": status_class,
            "symbol": symbol,
        })

        if recipient.fecha_visualizacion:
            activity_events.append({
                "occurred_at": recipient.fecha_visualizacion,
                "description": f"{recipient.usuario} visualizó el documento",
                "kind": "viewed",
                "order": 1,
            })
        if signature is not None and signature.fecha_firma:
            activity_events.append({
                "occurred_at": signature.fecha_firma,
                "description": f"{recipient.usuario} firmó el documento",
                "kind": "signed",
                "order": 2,
            })

    activity_events.sort(key=lambda event: (event["occurred_at"], event["order"]))
    total = len(recipients)
    completed = sum(
        recipient.estado == DestinatarioDocumento.Estado.FIRMADO
        for recipient in recipients
    )
    resultado_disponible = DocumentoResultado.objects.filter(envio_id=envio.pk).exists()

    return {
        "envio": envio,
        "tracking_recipients": tracking_recipients,
        "signature_total": total,
        "signature_completed": completed,
        "signature_pending": total - completed,
        "signature_percentage": round(completed * 100 / total) if total else 0,
        "all_signed": total > 0 and completed == total,
        "activity_events": activity_events,
        "last_activity": activity_events[-1] if activity_events else None,
        "resultado_disponible": resultado_disponible,
        "signed_document_download_url": (
            reverse("documentos:download_result", args=[envio.pk])
            if resultado_disponible
            else None
        ),
    }


def recipient_documents_queryset(user):
    return (
        DestinatarioDocumento.objects.filter(
            usuario=user,
            envio__estado=EnvioDocumento.Estado.ENVIADO,
        )
        .select_related("envio__documento", "envio__remitente", "envio__resultado")
        .order_by("-envio__fecha_envio", "-fecha_agregado")
    )


def recipient_documents_context(user, selected_status="todos"):
    if selected_status not in {"todos", "pendientes", "completados"}:
        selected_status = "todos"

    queryset = recipient_documents_queryset(user)
    counts = queryset.aggregate(
        document_count=Count("pk"),
        pending_count=Count(
            "pk",
            filter=Q(estado__in=PENDING_RECIPIENT_STATES),
        ),
        completed_count=Count(
            "pk",
            filter=Q(estado=DestinatarioDocumento.Estado.FIRMADO),
        ),
    )

    if selected_status == "pendientes":
        documents = queryset.filter(estado__in=PENDING_RECIPIENT_STATES)
    elif selected_status == "completados":
        documents = queryset.filter(estado=DestinatarioDocumento.Estado.FIRMADO)
    else:
        documents = queryset

    return {
        "documents": documents,
        "selected_status": selected_status,
        **counts,
    }

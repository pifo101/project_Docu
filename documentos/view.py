import json
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Prefetch
from django.http import FileResponse, Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_http_methods, require_POST
from pypdf import PdfReader
from pypdf.errors import PdfReadError

from usuarios.models import Cargo

from .forms import DocumentoForm
from .models import CampoFirma, DestinatarioDocumento, Documento, EnvioDocumento
from .services import (
    document_tracking_context,
    recipient_documents_context,
    sender_documents_context,
)


def _documento_de_presidente(request, pk):
    if (
        request.user.cargo_id != Cargo.Codigo.PRESIDENTE
        or not request.user.comite_id
        or not request.user.comite.activo
    ):
        raise PermissionDenied
    return get_object_or_404(Documento, pk=pk, propietario=request.user)


def _integrantes_del_comite(request):
    return (
        request.user.comite.usuarios
        .filter(is_active=True)
        .exclude(pk=request.user.pk)
        .select_related("cargo")
        .order_by("first_name", "last_name", "email")
    )


def _preparar_envio(documento, request):
    integrantes = list(_integrantes_del_comite(request))
    with transaction.atomic():
        envio, creado = EnvioDocumento.objects.select_for_update().get_or_create(
            documento=documento,
            defaults={
                "remitente": request.user,
                "estado": EnvioDocumento.Estado.PREPARACION,
            },
        )
        if not creado and (
            envio.estado != EnvioDocumento.Estado.PREPARACION
            or envio.remitente_id != request.user.pk
        ):
            raise PermissionDenied

        ids_integrantes = {integrante.pk for integrante in integrantes}
        envio.destinatarios.exclude(usuario_id__in=ids_integrantes).delete()
        destinatarios_existentes = set(
            envio.destinatarios.values_list("usuario_id", flat=True)
        )
        DestinatarioDocumento.objects.bulk_create([
            DestinatarioDocumento(
                envio=envio,
                usuario=integrante,
                estado=DestinatarioDocumento.Estado.BORRADOR,
            )
            for integrante in integrantes
            if integrante.pk not in destinatarios_existentes
        ])
    return envio


def _numero_paginas(documento):
    try:
        with documento.archivo.open("rb") as archivo:
            total_paginas = len(PdfReader(archivo).pages)
            if total_paginas < 1:
                raise ValueError("El PDF no contiene páginas.")
            return total_paginas
    except (OSError, PdfReadError, TypeError, ValueError) as error:
        raise ValidationError("No se pudo determinar el número de páginas del PDF.") from error


def _campo_serializado(campo):
    usuario = campo.destinatario.usuario
    return {
        "id": campo.pk,
        "type": "signature",
        "page": campo.pagina,
        "x": float(campo.x),
        "y": float(campo.y),
        "width": float(campo.ancho),
        "height": float(campo.alto),
        "recipient_id": campo.destinatario_id,
        "recipient_name": str(usuario),
    }


def documents_view(request):
    context = sender_documents_context(request.user) if request.user.is_authenticated else {}
    context.update({
        "documentos": context.get("owned_documents"),
        "documento_max_file_size": settings.DOCUMENTO_MAX_FILE_SIZE,
        "documento_max_file_size_mb": settings.DOCUMENTO_MAX_FILE_SIZE // (1024 * 1024),
    })
    return render(request, "documentos/documents.html", context)


@login_required
@require_http_methods(["GET", "POST"])
def committee_recipients_view(request, pk):
    documento = _documento_de_presidente(request, pk)
    integrantes = _integrantes_del_comite(request)
    if request.method == "POST":
        _preparar_envio(documento, request)
        return redirect("documentos:document_editor", pk=documento.pk)
    return render(request, "documentos/recipients.html", {
        "documento": documento,
        "comite": request.user.comite,
        "integrantes": integrantes,
    })


@login_required
def send_review_view(request, pk):
    documento = _documento_de_presidente(request, pk)
    envio = EnvioDocumento.objects.filter(documento=documento).first()
    if envio is None:
        messages.info(request, "Primero asigna un campo de firma a cada destinatario.")
        return redirect("documentos:committee_recipients", pk=documento.pk)
    if envio.estado == EnvioDocumento.Estado.ENVIADO:
        messages.info(request, "Este documento ya fue enviado al comité.")
        return redirect("documentos:document_detail", pk=documento.pk)
    destinatarios = list(
        envio.destinatarios.select_related("usuario__cargo")
        .prefetch_related("campos_firma")
        .order_by("usuario__first_name", "usuario__last_name", "usuario__email")
    )
    campos_asignados = sum(bool(destinatario.campos_firma.all()) for destinatario in destinatarios)
    return render(request, "documentos/review.html", {
        "documento": documento,
        "envio": envio,
        "comite": request.user.comite,
        "destinatarios": destinatarios,
        "campos_asignados": campos_asignados,
        "listo_para_enviar": bool(destinatarios) and campos_asignados == len(destinatarios),
    })


@login_required
@require_POST
def send_document_view(request, pk):
    documento = _documento_de_presidente(request, pk)

    with transaction.atomic():
        envio = (
            EnvioDocumento.objects.select_for_update()
            .filter(documento=documento)
            .first()
        )
        if envio is None:
            messages.error(request, "Primero prepara el envío y asigna los campos de firma.")
            return redirect("documentos:committee_recipients", pk=documento.pk)
        if envio.remitente_id != request.user.pk:
            raise PermissionDenied
        if envio.estado == EnvioDocumento.Estado.ENVIADO:
            messages.info(request, "Este documento ya fue enviado al comité.")
            return redirect("documentos:document_detail", pk=documento.pk)

        destinatarios = list(
            envio.destinatarios.select_for_update().select_related(
                "usuario__comite"
            )
        )
        if not destinatarios:
            messages.error(request, "El envío no tiene destinatarios preparados.")
            return redirect("documentos:send_review", pk=documento.pk)
        if any(
            destinatario.estado != DestinatarioDocumento.Estado.BORRADOR
            for destinatario in destinatarios
        ):
            messages.error(request, "Los destinatarios no están en un estado válido para enviar.")
            return redirect("documentos:send_review", pk=documento.pk)
        if any(
            not destinatario.usuario.is_active
            or destinatario.usuario.comite_id != request.user.comite_id
            or not destinatario.usuario.comite.activo
            for destinatario in destinatarios
        ):
            raise PermissionDenied

        destinatarios_con_campo = set(
            CampoFirma.objects.filter(destinatario__envio=envio).values_list(
                "destinatario_id", flat=True
            )
        )
        faltantes = [
            str(destinatario.usuario)
            for destinatario in destinatarios
            if destinatario.pk not in destinatarios_con_campo
        ]
        if faltantes:
            messages.error(
                request,
                "Falta un campo de firma para: " + ", ".join(faltantes) + ".",
            )
            return redirect("documentos:send_review", pk=documento.pk)

        envio.estado = EnvioDocumento.Estado.ENVIADO
        envio.fecha_envio = timezone.now()
        envio.save(update_fields=("estado", "fecha_envio"))
        envio.destinatarios.update(estado=DestinatarioDocumento.Estado.PENDIENTE)

    messages.success(
        request,
        f"El documento se envió a {len(destinatarios)} integrante(s) del comité.",
    )
    return redirect("documentos:document_detail", pk=documento.pk)


@login_required
def upload_document_view(request):
    form = DocumentoForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        documento = form.save(commit=False)
        documento.propietario = request.user
        documento.nombre_original = form.cleaned_data["archivo"].name
        documento.save()
        messages.success(request, "El documento se cargó correctamente.")
        return redirect("documentos:list")
    context = sender_documents_context(request.user)
    context.update({
        "documentos": context["owned_documents"],
        "form": form,
        "documento_max_file_size": settings.DOCUMENTO_MAX_FILE_SIZE,
        "documento_max_file_size_mb": settings.DOCUMENTO_MAX_FILE_SIZE // (1024 * 1024),
    })
    return render(request, "documentos/documents.html", context)


@login_required
def owned_document_detail_view(request, pk):
    tracking_recipients = DestinatarioDocumento.objects.select_related(
        "usuario",
        "firma",
    ).order_by("usuario__first_name", "usuario__last_name", "usuario__email")
    documento = get_object_or_404(
        Documento.objects.select_related("envio").prefetch_related(
            Prefetch("envio__destinatarios", queryset=tracking_recipients)
        ),
        pk=pk,
        propietario=request.user,
    )
    context = sender_documents_context(request.user)
    context["documento"] = documento
    context.update(document_tracking_context(documento))
    return render(request, "documentos/document_detail.html", context)


@login_required
def download_document_view(request, pk):
    documento = get_object_or_404(Documento, pk=pk, propietario=request.user)
    if not documento.archivo:
        raise Http404
    return FileResponse(documento.archivo.open("rb"), as_attachment=True, filename=documento.nombre_original)


@login_required
def received_document_view(request, pk):
    destinatario = get_object_or_404(
        DestinatarioDocumento.objects.select_related("envio__documento"),
        pk=pk,
        usuario=request.user,
        envio__estado=EnvioDocumento.Estado.ENVIADO,
    )
    documento = destinatario.envio.documento
    archivo = documento.archivo.open("rb")
    if destinatario.estado == DestinatarioDocumento.Estado.PENDIENTE:
        destinatario.estado = DestinatarioDocumento.Estado.VISTO
        destinatario.fecha_visualizacion = timezone.now()
        destinatario.save(update_fields=("estado", "fecha_visualizacion"))

    return FileResponse(
        archivo,
        content_type="application/pdf",
        filename=documento.nombre_original,
    )


def document_detail_view(request):
    return render(request, "documentos/detail.html")


def recipients_view(request):
    return render(request, "documentos/recipients.html")


def editor_view(request):
    return render(request, "documentos/editor.html")


@login_required
def document_editor_view(request, pk):
    documento = _documento_de_presidente(request, pk)
    envio = EnvioDocumento.objects.filter(documento=documento).first()
    if envio is None:
        messages.info(request, "Confirma los destinatarios antes de abrir el editor.")
        return redirect("documentos:committee_recipients", pk=documento.pk)
    if (
        envio.estado != EnvioDocumento.Estado.PREPARACION
        or envio.remitente_id != request.user.pk
    ):
        raise PermissionDenied
    destinatarios = list(envio.destinatarios.select_related("usuario").order_by(
        "usuario__first_name", "usuario__last_name", "usuario__email"
    ))
    return render(request, "documentos/editor.html", {
        "documento": documento,
        "destinatarios": destinatarios,
        "destinatarios_editor": [
            {
                "id": destinatario.pk,
                "name": str(destinatario.usuario),
                "email": destinatario.usuario.email,
            }
            for destinatario in destinatarios
        ],
    })


@login_required
@require_http_methods(["GET", "POST"])
def signature_fields_view(request, pk):
    documento = _documento_de_presidente(request, pk)
    envio = get_object_or_404(
        EnvioDocumento,
        documento=documento,
        estado=EnvioDocumento.Estado.PREPARACION,
    )
    campos = CampoFirma.objects.filter(
        destinatario__envio=envio
    ).select_related("destinatario__usuario")

    if request.method == "GET":
        return JsonResponse({"fields": [_campo_serializado(campo) for campo in campos]})

    try:
        payload = json.loads(request.body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({"error": "El contenido JSON no es válido."}, status=400)

    datos_campos = payload.get("fields") if isinstance(payload, dict) else None
    if not isinstance(datos_campos, list):
        return JsonResponse({"error": "La lista de campos es obligatoria."}, status=400)

    try:
        total_paginas = _numero_paginas(documento)
    except ValidationError as error:
        return JsonResponse({"error": error.messages[0]}, status=422)

    destinatarios = {
        destinatario.pk: destinatario
        for destinatario in envio.destinatarios.select_related("usuario")
    }
    campos_existentes = {campo.pk: campo for campo in campos}
    ids_recibidos = set()
    destinatarios_recibidos = set()
    campos_validados = []

    for datos in datos_campos:
        if not isinstance(datos, dict) or datos.get("type", "signature") != "signature":
            return JsonResponse({"error": "Sólo se admiten campos de firma."}, status=400)

        campo_id = datos.get("id")
        if campo_id is not None:
            if isinstance(campo_id, bool) or not isinstance(campo_id, int) or campo_id not in campos_existentes:
                return JsonResponse({"error": "El campo indicado no pertenece al documento."}, status=400)
            if campo_id in ids_recibidos:
                return JsonResponse({"error": "No se puede repetir un campo."}, status=400)
            ids_recibidos.add(campo_id)

        destinatario_id = datos.get("recipient_id")
        if isinstance(destinatario_id, bool) or not isinstance(destinatario_id, int) or destinatario_id not in destinatarios:
            return JsonResponse({"error": "El destinatario no pertenece al documento."}, status=400)
        if destinatario_id in destinatarios_recibidos:
            return JsonResponse(
                {"error": "Cada destinatario puede tener un solo campo de firma."},
                status=400,
            )
        destinatarios_recibidos.add(destinatario_id)

        pagina = datos.get("page")
        if isinstance(pagina, bool) or not isinstance(pagina, int) or not 1 <= pagina <= total_paginas:
            return JsonResponse({"error": "La página indicada no es válida."}, status=400)

        nombres_coordenadas = ("x", "y", "width", "height")
        if any(
            isinstance(datos.get(nombre), bool)
            or not isinstance(datos.get(nombre), (int, float))
            for nombre in nombres_coordenadas
        ):
            return JsonResponse({"error": "Las coordenadas no son válidas."}, status=400)
        try:
            valores = {
                nombre: Decimal(str(datos[nombre]))
                for nombre in nombres_coordenadas
            }
        except (KeyError, InvalidOperation, ValueError):
            return JsonResponse({"error": "Las coordenadas no son válidas."}, status=400)
        if len(valores) != 4 or not all(valor.is_finite() for valor in valores.values()):
            return JsonResponse({"error": "Las coordenadas no son válidas."}, status=400)

        campo = campos_existentes.get(campo_id, CampoFirma())
        campo.destinatario = destinatarios[destinatario_id]
        campo.pagina = pagina
        campo.x = valores["x"]
        campo.y = valores["y"]
        campo.ancho = valores["width"]
        campo.alto = valores["height"]
        try:
            campo.full_clean(validate_constraints=False)
        except ValidationError:
            return JsonResponse(
                {"error": "Las coordenadas deben estar normalizadas y dentro de la página."},
                status=400,
            )
        campos_validados.append(campo)

    with transaction.atomic():
        envio_bloqueado = get_object_or_404(
            EnvioDocumento.objects.select_for_update(),
            pk=envio.pk,
            estado=EnvioDocumento.Estado.PREPARACION,
        )
        CampoFirma.objects.filter(destinatario__envio=envio_bloqueado).exclude(
            pk__in=[campo.pk for campo in campos_validados if campo.pk]
        ).delete()
        for campo in campos_validados:
            campo.save()

    return JsonResponse({
        "fields": [_campo_serializado(campo) for campo in campos_validados]
    })


def review_view(request):
    return render(request, "documentos/review.html")


@login_required
def pending_view(request):
    return redirect("documentos:user_pending")


@login_required
def user_documents_view(request, status=None):
    selected_status = status or request.GET.get("estado", "todos")
    context = recipient_documents_context(request.user, selected_status)
    return render(request, "documentos/user_documents.html", context)

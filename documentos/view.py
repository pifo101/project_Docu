from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from usuarios.models import Cargo

from .forms import DocumentoForm
from .models import DestinatarioDocumento, Documento, EnvioDocumento


def _documento_de_presidente(request, pk):
    if request.user.cargo_id != Cargo.Codigo.PRESIDENTE or not request.user.comite_id:
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


def documents_view(request):
    documentos = Documento.objects.filter(propietario=request.user) if request.user.is_authenticated else None
    return render(request, "documentos/documents.html", {
        "documentos": documentos,
        "documento_max_file_size_mb": settings.DOCUMENTO_MAX_FILE_SIZE // (1024 * 1024),
    })


@login_required
def committee_recipients_view(request, pk):
    documento = _documento_de_presidente(request, pk)
    integrantes = _integrantes_del_comite(request)
    return render(request, "documentos/recipients.html", {
        "documento": documento,
        "comite": request.user.comite,
        "integrantes": integrantes,
    })


@login_required
def send_review_view(request, pk):
    documento = _documento_de_presidente(request, pk)
    integrantes = _integrantes_del_comite(request)
    return render(request, "documentos/review.html", {
        "documento": documento,
        "comite": request.user.comite,
        "integrantes": integrantes,
    })


@login_required
@require_POST
def send_document_view(request, pk):
    documento = _documento_de_presidente(request, pk)
    integrantes = list(_integrantes_del_comite(request))
    if not integrantes:
        messages.error(request, "El comité no tiene otros integrantes activos.")
        return redirect("documentos:send_review", pk=documento.pk)

    with transaction.atomic():
        envio, creado = EnvioDocumento.objects.get_or_create(
            documento=documento,
            defaults={"remitente": request.user},
        )
        if creado:
            DestinatarioDocumento.objects.bulk_create([
                DestinatarioDocumento(envio=envio, usuario=integrante)
                for integrante in integrantes
            ])

    if not creado:
        messages.info(request, "Este documento ya fue enviado al comité.")
        return redirect("documentos:list")

    messages.success(
        request,
        f"El documento se envió a {len(integrantes)} integrante(s) del comité.",
    )
    return redirect("documentos:list")


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
    return render(request, "documentos/documents.html", {
        "documentos": Documento.objects.filter(propietario=request.user),
        "form": form,
        "documento_max_file_size_mb": settings.DOCUMENTO_MAX_FILE_SIZE // (1024 * 1024),
    })


@login_required
def owned_document_detail_view(request, pk):
    documento = get_object_or_404(Documento, pk=pk, propietario=request.user)
    return render(request, "documentos/document_detail.html", {"documento": documento})


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


def review_view(request):
    return render(request, "documentos/review.html")


@login_required
def pending_view(request):
    destinatarios = (
        DestinatarioDocumento.objects
        .filter(usuario=request.user)
        .select_related("envio__documento", "envio__remitente")
    )
    return render(request, "documentos/pending.html", {"destinatarios": destinatarios})

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.conf import settings
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render

from .forms import DocumentoForm
from .models import Documento


def documents_view(request):
    documentos = Documento.objects.filter(propietario=request.user) if request.user.is_authenticated else None
    return render(request, "documentos/documents.html", {
        "documentos": documentos,
        "documento_max_file_size_mb": settings.DOCUMENTO_MAX_FILE_SIZE // (1024 * 1024),
    })


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


def document_detail_view(request):
    return render(request, "documentos/detail.html")


def recipients_view(request):
    return render(request, "documentos/recipients.html")


def editor_view(request):
    return render(request, "documentos/editor.html")


def review_view(request):
    return render(request, "documentos/review.html")


def pending_view(request):
    return render(request, "documentos/pending.html")

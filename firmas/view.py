from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import IntegrityError, transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from documentos.models import DestinatarioDocumento

from .forms import FirmaForm
from .models import Firma


def request_view(request):
    return render(request, "firmas/request.html")


def sign_view(request):
    return render(request, "firmas/sign.html", {"demo": True})


def completed_view(request):
    return render(request, "firmas/completed.html")


@login_required
@require_http_methods(["GET", "POST"])
def recipient_sign_view(request, pk):
    destinatario = get_object_or_404(
        DestinatarioDocumento.objects.select_related(
            "envio__documento", "envio__remitente", "usuario"
        ),
        pk=pk,
        usuario=request.user,
    )

    if destinatario.estado == DestinatarioDocumento.Estado.FIRMADO or Firma.objects.filter(
        destinatario=destinatario
    ).exists():
        messages.info(request, "Ya registraste tu firma para este documento.")
        return redirect("documentos:user_completed")

    if request.method == "GET":
        if destinatario.estado != DestinatarioDocumento.Estado.PENDIENTE:
            if destinatario.estado != DestinatarioDocumento.Estado.VISTO:
                return redirect("documentos:pending")
        else:
            destinatario.estado = DestinatarioDocumento.Estado.VISTO
            destinatario.fecha_visualizacion = timezone.now()
            destinatario.save(update_fields=("estado", "fecha_visualizacion"))
        form = FirmaForm()
    else:
        form = FirmaForm(request.POST)
        if form.is_valid():
            try:
                with transaction.atomic():
                    bloqueado = get_object_or_404(
                        DestinatarioDocumento.objects.select_for_update(),
                        pk=pk,
                        usuario=request.user,
                    )
                    if bloqueado.estado == DestinatarioDocumento.Estado.FIRMADO or Firma.objects.filter(
                        destinatario=bloqueado
                    ).exists():
                        messages.info(request, "Ya registraste tu firma para este documento.")
                        return redirect("documentos:user_completed")
                    if bloqueado.estado not in (
                        DestinatarioDocumento.Estado.PENDIENTE,
                        DestinatarioDocumento.Estado.VISTO,
                    ):
                        form.add_error(None, "El documento no se encuentra en un estado válido para firmar.")
                    else:
                        if bloqueado.estado == DestinatarioDocumento.Estado.PENDIENTE:
                            bloqueado.fecha_visualizacion = timezone.now()
                        Firma.objects.create(
                            destinatario=bloqueado,
                            imagen=form.cleaned_data["firma"],
                            consentimiento=form.cleaned_data["consentimiento"],
                        )
                        bloqueado.estado = DestinatarioDocumento.Estado.FIRMADO
                        bloqueado.save(update_fields=("estado", "fecha_visualizacion"))
            except IntegrityError:
                messages.info(request, "Ya registraste tu firma para este documento.")
                return redirect("documentos:user_completed")
            if not form.errors:
                messages.success(request, "Tu firma y aceptación se registraron correctamente.")
                return redirect("documentos:user_completed")

    return render(request, "firmas/sign.html", {
        "destinatario": destinatario,
        "documento": destinatario.envio.documento,
        "form": form,
    })

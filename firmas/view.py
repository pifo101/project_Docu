from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.db import IntegrityError, transaction
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.cache import patch_cache_control
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from auditoria.models import EventoAuditoria
from auditoria.services import registrar_evento
from documentos.models import DestinatarioDocumento, EnvioDocumento
from documentos.services import ResultadoPDFError, generar_resultado_si_completo
from usuarios.decorators import email_verificado_required

from .forms import FirmaForm, FirmaPerfilForm
from .models import Firma, FirmaPerfil


def _intentar_generar_resultado(request, envio_id):
    try:
        return generar_resultado_si_completo(
            envio_id,
            actor=request.user,
            request=request,
        )
    except ResultadoPDFError:
        messages.warning(request, "No se pudo generar el PDF resultante.")
        return None


def _render_documento_destinatario(
    request,
    destinatario,
    campos_firma,
    form=None,
    firma_perfil=None,
    readonly=False,
    already_signed=False,
    show_result=False,
):
    pdf_view_url = reverse(
        "documentos:view_result" if show_result else "documentos:received_document",
        args=[destinatario.envio_id if show_result else destinatario.pk],
    )
    return render(request, "firmas/sign.html", {
        "destinatario": destinatario,
        "documento": destinatario.envio.documento,
        "form": form,
        "firma_perfil": firma_perfil,
        "readonly": readonly,
        "protected_viewer": destinatario.usuario_id != destinatario.envio.remitente_id,
        "already_signed": already_signed,
        "show_result": show_result,
        "pdf_view_url": pdf_view_url,
        "campo_firma": campos_firma[0],
        "campos_firma": [] if show_result else campos_firma,
        "campos_firma_data": [
            {
                "page": campo.pagina,
                "x": float(campo.x),
                "y": float(campo.y),
                "width": float(campo.ancho),
                "height": float(campo.alto),
            }
            for campo in (() if show_result else campos_firma)
        ],
    })


def request_view(request):
    return render(request, "firmas/request.html")


def sign_view(request):
    return render(request, "firmas/sign.html", {"demo": True})


def completed_view(request):
    return render(request, "firmas/completed.html")


@login_required
@email_verificado_required
@require_POST
def profile_signature_save_view(request):
    form = FirmaPerfilForm(request.POST, request.FILES)
    if not form.is_valid():
        error = next(iter(form.errors.values()))[0]
        messages.error(request, error)
        return redirect("usuarios:profile")

    with transaction.atomic():
        usuario = get_user_model().objects.select_for_update().get(pk=request.user.pk)
        FirmaPerfil.objects.update_or_create(
            usuario=usuario,
            defaults={
                "imagen": form.image_bytes,
                "formato": form.image_format,
            },
        )
    messages.success(request, "Tu firma guardada se actualizó correctamente.")
    return redirect("usuarios:profile")


@login_required
@email_verificado_required
@require_POST
def profile_signature_delete_view(request):
    FirmaPerfil.objects.filter(usuario=request.user).delete()
    messages.success(request, "Tu firma guardada se eliminó correctamente.")
    return redirect("usuarios:profile")


@login_required
@email_verificado_required
@require_GET
def profile_signature_preview_view(request):
    firma_perfil = get_object_or_404(FirmaPerfil, usuario=request.user)
    response = HttpResponse(bytes(firma_perfil.imagen), content_type=firma_perfil.formato)
    response["Content-Disposition"] = "inline"
    response["X-Content-Type-Options"] = "nosniff"
    patch_cache_control(response, private=True, no_store=True)
    return response


@login_required
@email_verificado_required
@require_http_methods(["GET", "POST"])
def recipient_sign_view(request, pk):
    destinatario = get_object_or_404(
        DestinatarioDocumento.objects.select_related(
            "envio__documento", "envio__remitente", "usuario"
        ).prefetch_related("campos_firma"),
        pk=pk,
        usuario=request.user,
        envio__estado=EnvioDocumento.Estado.ENVIADO,
    )
    campos_firma = list(destinatario.campos_firma.all())
    if not campos_firma:
        return HttpResponse(
            "Este envío no tiene una ubicación de firma asignada. Contacta al remitente.",
            status=409,
        )

    if destinatario.estado == DestinatarioDocumento.Estado.FIRMADO or Firma.objects.filter(
        destinatario=destinatario
    ).exists():
        resultado = _intentar_generar_resultado(request, destinatario.envio_id)
        if request.method == "GET":
            return _render_documento_destinatario(
                request,
                destinatario,
                campos_firma,
                readonly=True,
                already_signed=True,
                show_result=resultado is not None,
            )
        messages.info(request, "Ya registraste tu firma para este documento.")
        return redirect("documentos:user_completed")
    firma_perfil = FirmaPerfil.objects.filter(usuario=request.user).first()
    if request.method == "GET":
        with transaction.atomic():
            destinatario = get_object_or_404(
                DestinatarioDocumento.objects.select_for_update().select_related(
                    "envio__documento", "envio__remitente", "usuario"
                ),
                pk=pk,
                usuario=request.user,
                envio__estado=EnvioDocumento.Estado.ENVIADO,
            )
            if destinatario.estado == DestinatarioDocumento.Estado.FIRMADO or Firma.objects.filter(
                destinatario=destinatario
            ).exists():
                ya_firmado = True
            elif destinatario.estado == DestinatarioDocumento.Estado.PENDIENTE:
                ya_firmado = False
                destinatario.estado = DestinatarioDocumento.Estado.VISTO
                destinatario.fecha_visualizacion = timezone.now()
                destinatario.save(update_fields=("estado", "fecha_visualizacion"))
                registrar_evento(
                    tipo=EventoAuditoria.Tipo.DOCUMENTO_VISUALIZADO,
                    envio=destinatario.envio,
                    request=request,
                    informacion_adicional={"destinatario_id": destinatario.pk},
                )
            elif destinatario.estado == DestinatarioDocumento.Estado.VISTO:
                ya_firmado = False
            else:
                return redirect("documentos:user_pending")
        if ya_firmado:
            resultado = _intentar_generar_resultado(request, destinatario.envio_id)
            return _render_documento_destinatario(
                request,
                destinatario,
                campos_firma,
                readonly=True,
                already_signed=True,
                show_result=resultado is not None,
            )
        form = FirmaForm()
    else:
        form = FirmaForm(request.POST)
        if form.is_valid():
            envio_id = None
            try:
                with transaction.atomic():
                    bloqueado = get_object_or_404(
                        DestinatarioDocumento.objects.select_for_update().select_related("envio"),
                        pk=pk,
                        usuario=request.user,
                        envio__estado=EnvioDocumento.Estado.ENVIADO,
                    )
                    if bloqueado.estado == DestinatarioDocumento.Estado.FIRMADO or Firma.objects.filter(
                        destinatario=bloqueado
                    ).exists():
                        messages.info(request, "Ya registraste tu firma para este documento.")
                        return redirect("documentos:user_completed")
                    if not bloqueado.campos_firma.exists():
                        form.add_error(
                            None,
                            "El envío no tiene una ubicación de firma asignada.",
                        )
                    elif bloqueado.estado not in (
                        DestinatarioDocumento.Estado.PENDIENTE,
                        DestinatarioDocumento.Estado.VISTO,
                    ):
                        form.add_error(None, "El documento no se encuentra en un estado válido para firmar.")
                    else:
                        visualizacion_nueva = (
                            bloqueado.estado == DestinatarioDocumento.Estado.PENDIENTE
                        )
                        if bloqueado.estado == DestinatarioDocumento.Estado.PENDIENTE:
                            bloqueado.fecha_visualizacion = timezone.now()
                        if form.cleaned_data["metodo"] == Firma.Metodo.PERFIL:
                            firma_perfil_bloqueada = (
                                FirmaPerfil.objects.select_for_update()
                                .filter(usuario=request.user)
                                .first()
                            )
                            if firma_perfil_bloqueada is None:
                                form.add_error(
                                    "metodo",
                                    "No tienes una firma guardada disponible.",
                                )
                                imagen = None
                                formato = None
                            else:
                                imagen = bytes(firma_perfil_bloqueada.imagen)
                                formato = firma_perfil_bloqueada.formato
                        else:
                            imagen = form.cleaned_data["firma"]
                            formato = "image/png"
                        if not form.errors:
                            firma = Firma.objects.create(
                                destinatario=bloqueado,
                                imagen=imagen,
                                formato=formato,
                                metodo=form.cleaned_data["metodo"],
                                consentimiento=form.cleaned_data["consentimiento"],
                            )
                            bloqueado.estado = DestinatarioDocumento.Estado.FIRMADO
                            bloqueado.save(update_fields=("estado", "fecha_visualizacion"))
                            if visualizacion_nueva:
                                registrar_evento(
                                    tipo=EventoAuditoria.Tipo.DOCUMENTO_VISUALIZADO,
                                    envio=bloqueado.envio,
                                    request=request,
                                    informacion_adicional={"destinatario_id": bloqueado.pk},
                                )
                            registrar_evento(
                                tipo=EventoAuditoria.Tipo.FIRMA_COMPLETADA,
                                envio=bloqueado.envio,
                                request=request,
                                informacion_adicional={
                                    "destinatario_id": bloqueado.pk,
                                    "firma_id": firma.pk,
                                    "metodo": firma.metodo,
                                },
                            )
                            envio_id = bloqueado.envio_id
            except IntegrityError:
                if Firma.objects.filter(destinatario_id=pk).exists():
                    messages.info(request, "Ya registraste tu firma para este documento.")
                    return redirect("documentos:user_completed")
                raise
            if not form.errors:
                _intentar_generar_resultado(request, envio_id)
                messages.success(request, "Tu firma y aceptación se registraron correctamente.")
                return redirect("documentos:user_completed")

    return _render_documento_destinatario(
        request,
        destinatario,
        campos_firma,
        form=form,
        firma_perfil=firma_perfil,
    )

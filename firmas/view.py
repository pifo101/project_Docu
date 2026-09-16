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
from documentos.models import CampoFirma, DestinatarioDocumento, EnvioDocumento
from documentos.services import ResultadoPDFError, generar_resultado_si_completo
from .forms import FirmaForm, FirmaPerfilForm
from .models import Firma, FirmaPerfil


TIPOS_CAMPO_FRONTEND = {
    CampoFirma.Tipo.FIRMA: "signature",
    CampoFirma.Tipo.NOMBRE: "name",
    CampoFirma.Tipo.FECHA: "date",
    CampoFirma.Tipo.TEXTO: "text",
    CampoFirma.Tipo.INICIALES: "initials",
    CampoFirma.Tipo.CHECKBOX: "checkbox",
}


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


def _iniciales_usuario(usuario):
    partes = [usuario.first_name.strip(), usuario.last_name.strip()]
    iniciales = "".join(parte[0] for parte in partes if parte).upper()
    return iniciales or usuario.email[:2].upper()


def _datos_campos_destinatario(destinatario, campos):
    nombre = destinatario.usuario.get_full_name().strip() or destinatario.usuario.email
    iniciales = _iniciales_usuario(destinatario.usuario)
    fecha = timezone.localdate().strftime("%d/%m/%Y")
    datos = []
    for campo in campos:
        valor = campo.valor
        if campo.tipo == CampoFirma.Tipo.NOMBRE:
            valor = valor or nombre
        elif campo.tipo == CampoFirma.Tipo.INICIALES:
            valor = valor or iniciales
        elif campo.tipo == CampoFirma.Tipo.FECHA:
            valor = valor or fecha
        datos.append({
            "id": campo.pk,
            "type": TIPOS_CAMPO_FRONTEND[campo.tipo],
            "label": campo.etiqueta or campo.get_tipo_display(),
            "required": campo.requerido,
            "value": valor or "",
            "checked": valor == "true",
            "page": campo.pagina,
            "x": float(campo.x),
            "y": float(campo.y),
            "width": float(campo.ancho),
            "height": float(campo.alto),
        })
    return datos


def _validar_y_preparar_valores(form, destinatario, campos, completado_en):
    recibidos = form.cleaned_data["valores_campos"]
    editables = {
        str(campo.pk): campo
        for campo in campos
        if campo.tipo in (CampoFirma.Tipo.TEXTO, CampoFirma.Tipo.CHECKBOX)
    }
    if set(recibidos) != set(editables):
        form.add_error("valores_campos", "Los campos enviados no corresponden al documento.")
        return []

    nombre = destinatario.usuario.get_full_name().strip() or destinatario.usuario.email
    iniciales = _iniciales_usuario(destinatario.usuario)
    fecha = timezone.localtime(completado_en).date().strftime("%d/%m/%Y")
    preparados = []
    for campo in campos:
        if campo.tipo == CampoFirma.Tipo.FIRMA:
            continue
        if campo.tipo == CampoFirma.Tipo.NOMBRE:
            valor = nombre
        elif campo.tipo == CampoFirma.Tipo.FECHA:
            valor = fecha
        elif campo.tipo == CampoFirma.Tipo.INICIALES:
            valor = iniciales
        elif campo.tipo == CampoFirma.Tipo.TEXTO:
            valor_recibido = recibidos[str(campo.pk)]
            if not isinstance(valor_recibido, str) or len(valor_recibido) > 500:
                form.add_error("valores_campos", "El texto de un campo no es válido.")
                continue
            valor = valor_recibido.strip()
            if campo.requerido and not valor:
                form.add_error("valores_campos", f'Completa el campo "{campo.etiqueta or "Texto"}".')
                continue
        else:
            valor_recibido = recibidos[str(campo.pk)]
            if not isinstance(valor_recibido, bool):
                form.add_error("valores_campos", "El valor de un checkbox no es válido.")
                continue
            if campo.requerido and not valor_recibido:
                form.add_error("valores_campos", f'Marca el campo "{campo.etiqueta or "Checkbox"}".')
                continue
            valor = "true" if valor_recibido else "false"
        campo.valor = valor
        campo.fecha_completado = completado_en
        preparados.append(campo)
    return preparados


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
    campos_visibles = [] if show_result else campos_firma
    campos_data = _datos_campos_destinatario(destinatario, campos_visibles)
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
        "campo_firma": next(
            campo for campo in campos_firma if campo.tipo == CampoFirma.Tipo.FIRMA
        ),
        "campos_firma": campos_visibles,
        "campos_interactivos": campos_data,
        "campos_firma_data": campos_data,
    })


def request_view(request):
    return render(request, "firmas/request.html")


def sign_view(request):
    return render(request, "firmas/sign.html", {"demo": True})


def completed_view(request):
    return render(request, "firmas/completed.html")


@login_required
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
@require_POST
def profile_signature_delete_view(request):
    FirmaPerfil.objects.filter(usuario=request.user).delete()
    messages.success(request, "Tu firma guardada se eliminó correctamente.")
    return redirect("usuarios:profile")


@login_required
@require_GET
def profile_signature_preview_view(request):
    firma_perfil = get_object_or_404(FirmaPerfil, usuario=request.user)
    response = HttpResponse(bytes(firma_perfil.imagen), content_type=firma_perfil.formato)
    response["Content-Disposition"] = "inline"
    response["X-Content-Type-Options"] = "nosniff"
    patch_cache_control(response, private=True, no_store=True)
    return response


@login_required
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
    if not any(campo.tipo == CampoFirma.Tipo.FIRMA for campo in campos_firma):
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
                        DestinatarioDocumento.objects.select_for_update().select_related("envio", "usuario"),
                        pk=pk,
                        usuario=request.user,
                        envio__estado=EnvioDocumento.Estado.ENVIADO,
                    )
                    if bloqueado.estado == DestinatarioDocumento.Estado.FIRMADO or Firma.objects.filter(
                        destinatario=bloqueado
                    ).exists():
                        messages.info(request, "Ya registraste tu firma para este documento.")
                        return redirect("documentos:user_completed")
                    campos_bloqueados = list(
                        bloqueado.campos_firma.select_for_update().order_by("pagina", "pk")
                    )
                    if not any(campo.tipo == CampoFirma.Tipo.FIRMA for campo in campos_bloqueados):
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
                        completado_en = timezone.now()
                        campos_preparados = _validar_y_preparar_valores(
                            form, bloqueado, campos_bloqueados, completado_en
                        )
                        visualizacion_nueva = (
                            bloqueado.estado == DestinatarioDocumento.Estado.PENDIENTE
                        )
                        if bloqueado.estado == DestinatarioDocumento.Estado.PENDIENTE:
                            bloqueado.fecha_visualizacion = timezone.now()
                        if not form.errors and form.cleaned_data["metodo"] == Firma.Metodo.PERFIL:
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
                            if campos_preparados:
                                CampoFirma.objects.bulk_update(
                                    campos_preparados, ("valor", "fecha_completado")
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

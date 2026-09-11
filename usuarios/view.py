from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model, login, logout
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.cache import patch_cache_control
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from documentos.models import EnvioDocumento
from documentos.services import (
    PENDING_RECIPIENT_STATES,
    recipient_documents_context,
    recipient_documents_queryset,
    sender_documents_context,
)
from firmas.models import FirmaPerfil

from .forms import (
    LoginUsuarioForm,
    ReenvioVerificacionForm,
    RegistroPublicoUsuarioForm,
)
from .models import Cargo
from .services import (
    enviar_correo_verificacion,
    token_verificacion_email_valido,
    verificar_token_email,
)


def _verification_pending_response(request):
    return render(
        request,
        "usuarios/email_verification_pending.html",
        {
            "resend_form": ReenvioVerificacionForm(
                initial={"email": request.user.email}
            )
        },
    )


@require_http_methods(["GET", "POST"])
def login_view(request):
    form = LoginUsuarioForm(request, data=request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.get_user()
        login(request, user)
        if not request.POST.get("remember"):
            request.session.set_expiry(0)
        next_url = request.POST.get("next")
        if next_url and url_has_allowed_host_and_scheme(
            next_url,
            allowed_hosts={request.get_host()},
            require_https=request.is_secure(),
        ):
            return redirect(next_url)
        return redirect("usuarios:dashboard")

    return render(request, "usuarios/login.html", {"form": form})


@require_http_methods(["GET", "POST"])
def register_view(request):
    form = RegistroPublicoUsuarioForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        usuario = form.save()
        try:
            enviar_correo_verificacion(usuario, request, limitar_reenvio=False)
            messages.success(
                request,
                "Cuenta creada. Revisa tu correo para verificarla.",
            )
        except Exception:
            messages.warning(
                request,
                "La cuenta fue creada, pero no se pudo enviar el correo. Puedes solicitar otro.",
            )
        return redirect("usuarios:login")

    return render(request, "usuarios/register.html", {"form": form})


@require_POST
def resend_verification_view(request):
    form = ReenvioVerificacionForm(request.POST)
    if form.is_valid():
        usuario = get_user_model().objects.filter(
            email__iexact=form.cleaned_data["email"],
            email_verificado=False,
            is_active=True,
        ).first()
        if usuario is not None:
            try:
                enviar_correo_verificacion(usuario, request)
            except Exception:
                pass
    messages.info(
        request,
        "Si existe una cuenta pendiente para ese correo, recibirás un nuevo enlace cuando sea posible.",
    )
    return redirect("usuarios:login")


@require_http_methods(["GET", "POST"])
def verify_email_view(request, token):
    if request.method == "GET":
        if not token_verificacion_email_valido(token):
            response = render(
                request,
                "usuarios/email_verification_result.html",
                {"verification_success": False},
                status=400,
            )
        else:
            response = render(
                request,
                "usuarios/email_verification_result.html",
                {"verification_pending": True},
            )
    else:
        usuario = verificar_token_email(token)
        if usuario is None:
            response = render(
                request,
                "usuarios/email_verification_result.html",
                {"verification_success": False},
                status=400,
            )
        else:
            if request.user.is_authenticated and request.user.pk == usuario.pk:
                request.user.email_verificado = True
                request.user.fecha_verificacion_email = usuario.fecha_verificacion_email
            response = render(
                request,
                "usuarios/email_verification_result.html",
                {"verification_success": True},
            )

    response["Referrer-Policy"] = "no-referrer"
    patch_cache_control(response, private=True, no_store=True)
    return response


@login_required
@require_GET
def dashboard_view(request):
    if not request.user.email_verificado:
        return _verification_pending_response(request)
    if (
        request.user.is_staff
        or request.user.is_superuser
        or request.user.cargo_id == Cargo.Codigo.PRESIDENTE
    ):
        context = sender_documents_context(request.user)
        documents = context["owned_documents"]
        context.update(
            recent_documents=documents[:5],
            preparation_documents=documents.filter(
                envio__estado=EnvioDocumento.Estado.PREPARACION
            )[:5],
            unsigned_documents=documents.filter(envio__isnull=True)[:5],
            documento_max_file_size=settings.DOCUMENTO_MAX_FILE_SIZE,
            documento_max_file_size_mb=settings.DOCUMENTO_MAX_FILE_SIZE // (1024 * 1024),
        )
        return render(request, "usuarios/dashboard.html", context)

    queryset = recipient_documents_queryset(request.user)
    context = recipient_documents_context(request.user)
    context.update(
        pending_documents=queryset.filter(
            estado__in=PENDING_RECIPIENT_STATES
        )[:5],
        recent_documents=queryset[:5],
    )
    return render(request, "documentos/user_dashboard.html", context)


@login_required
@require_GET
def profile_view(request):
    if not request.user.email_verificado:
        return _verification_pending_response(request)
    sender_portal = (
        request.user.is_staff
        or request.user.is_superuser
        or request.user.cargo_id == Cargo.Codigo.PRESIDENTE
    )
    context = (
        sender_documents_context(request.user)
        if sender_portal
        else recipient_documents_context(request.user)
    )
    context.update({
        "firma_perfil": FirmaPerfil.objects.filter(usuario=request.user).first(),
        "firma_perfil_max_file_size": settings.FIRMA_PERFIL_MAX_FILE_SIZE,
        "active_committee_member_count": request.user.comite.usuarios.filter(
            is_active=True
        ).count(),
    })
    template_name = "usuarios/profile.html" if sender_portal else "usuarios/user_account.html"
    return render(request, template_name, context)


@require_POST
@login_required
def logout_view(request):
    logout(request)
    return redirect("usuarios:login")

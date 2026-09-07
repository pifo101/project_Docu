from django.contrib.auth import login, logout
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from .forms import LoginUsuarioForm, RegistroUsuarioForm


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


def register_view(request):
    form = RegistroUsuarioForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        form.save()
        return redirect("usuarios:login")

    return render(request, "usuarios/register.html", {"form": form})


@login_required
def dashboard_view(request):
    if request.user.is_staff or request.user.is_superuser:
        return render(request, "usuarios/dashboard.html")

    context = {
        "documents": (),
        "pending_documents": (),
        "recent_documents": (),
        "document_count": 0,
        "pending_count": 0,
        "completed_count": 0,
        "document_backend_available": False,
    }
    return render(request, "documentos/user_dashboard.html", context)


@login_required
def profile_view(request):
    template_name = (
        "usuarios/profile.html"
        if request.user.is_staff or request.user.is_superuser
        else "usuarios/user_account.html"
    )
    return render(request, template_name)


@require_POST
@login_required
def logout_view(request):
    logout(request)
    return redirect("usuarios:login")

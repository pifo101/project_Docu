from django.contrib.auth import login
from django.shortcuts import redirect, render

from .forms import LoginUsuarioForm, RegistroUsuarioForm


def login_view(request):
    form = LoginUsuarioForm(request, data=request.POST or None)
    if request.method == "POST" and form.is_valid():
        login(request, form.get_user())
        if not request.POST.get("remember"):
            request.session.set_expiry(0)
        return redirect("usuarios:dashboard")

    return render(request, "usuarios/login.html", {"form": form})


def register_view(request):
    form = RegistroUsuarioForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        form.save()
        return redirect("usuarios:login")

    return render(request, "usuarios/register.html", {"form": form})


def dashboard_view(request):
    return render(request, "usuarios/dashboard.html")


def profile_view(request):
    return render(request, "usuarios/profile.html")

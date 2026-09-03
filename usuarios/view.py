from django.shortcuts import render


def login_view(request):
    return render(request, "usuarios/login.html")


def register_view(request):
    return render(request, "usuarios/register.html")

from django.shortcuts import render


def request_view(request):
    return render(request, "firmas/request.html")


def sign_view(request):
    return render(request, "firmas/sign.html")


def completed_view(request):
    return render(request, "firmas/completed.html")

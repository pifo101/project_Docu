from documentos.view import staff_required

from django.shortcuts import render


@staff_required
def request_view(request):
    return render(request, "firmas/request.html")


@staff_required
def sign_view(request):
    return render(request, "firmas/sign.html")


@staff_required
def completed_view(request):
    return render(request, "firmas/completed.html")

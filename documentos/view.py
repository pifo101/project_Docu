from django.shortcuts import render


def editor_view(request):
    return render(request, "documentos/editor.html")

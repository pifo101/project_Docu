from django.shortcuts import render


def documents_view(request):
    return render(request, "documentos/documents.html")


def document_detail_view(request):
    return render(request, "documentos/detail.html")


def recipients_view(request):
    return render(request, "documentos/recipients.html")


def editor_view(request):
    return render(request, "documentos/editor.html")


def review_view(request):
    return render(request, "documentos/review.html")


def pending_view(request):
    return render(request, "documentos/pending.html")

from functools import wraps

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import render


def staff_required(view_func):
    @wraps(view_func)
    @login_required
    def wrapped(request, *args, **kwargs):
        if not (request.user.is_staff or request.user.is_superuser):
            raise PermissionDenied
        return view_func(request, *args, **kwargs)

    return wrapped


@staff_required
def documents_view(request):
    return render(request, "documentos/documents.html")


@staff_required
def document_detail_view(request):
    return render(request, "documentos/detail.html")


@staff_required
def recipients_view(request):
    return render(request, "documentos/recipients.html")


@staff_required
def editor_view(request):
    return render(request, "documentos/editor.html")


@staff_required
def review_view(request):
    return render(request, "documentos/review.html")


@staff_required
def pending_view(request):
    return render(request, "documentos/pending.html")


@login_required
def user_documents_view(request, status=None):
    selected_status = status or request.GET.get("estado", "todos")
    if selected_status not in {"todos", "pendientes", "completados"}:
        selected_status = "todos"

    context = {
        "documents": (),
        "document_count": 0,
        "pending_count": 0,
        "completed_count": 0,
        "selected_status": selected_status,
        "document_backend_available": False,
    }
    return render(request, "documentos/user_documents.html", context)

from django.urls import path

from . import view


app_name = "documentos"

urlpatterns = [
    path("", view.documents_view, name="list"),
    path("mis-documentos/", view.user_documents_view, name="user_documents"),
    path(
        "mis-documentos/pendientes/",
        view.user_documents_view,
        {"status": "pendientes"},
        name="user_pending",
    ),
    path(
        "mis-documentos/completados/",
        view.user_documents_view,
        {"status": "completados"},
        name="user_completed",
    ),
    path("pendientes/", view.pending_view, name="pending"),
    path("nuevo/destinatarios/", view.recipients_view, name="recipients"),
    path("editor/", view.editor_view, name="editor"),
    path("revisar/", view.review_view, name="review"),
    path("contrato-servicios-2026/", view.document_detail_view, name="detail"),
]

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
    path("subir/", view.upload_document_view, name="upload"),
    path("<int:pk>/", view.owned_document_detail_view, name="document_detail"),
    path("<int:pk>/descargar/", view.download_document_view, name="download"),
    path("<int:pk>/destinatarios/", view.committee_recipients_view, name="committee_recipients"),
    path("<int:pk>/revisar-envio/", view.send_review_view, name="send_review"),
    path("<int:pk>/enviar/", view.send_document_view, name="send"),
    path("recibidos/<int:pk>/ver/", view.received_document_view, name="received_document"),
    path("pendientes/", view.pending_view, name="pending"),
    path("nuevo/destinatarios/", view.recipients_view, name="recipients"),
    path("editor/", view.editor_view, name="editor"),
    path("revisar/", view.review_view, name="review"),
    path("contrato-servicios-2026/", view.document_detail_view, name="detail"),
]

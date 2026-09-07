from django.urls import path

from . import view


app_name = "documentos"

urlpatterns = [
    path("", view.documents_view, name="list"),
    path("subir/", view.upload_document_view, name="upload"),
    path("<int:pk>/", view.owned_document_detail_view, name="document_detail"),
    path("<int:pk>/descargar/", view.download_document_view, name="download"),
    path("pendientes/", view.pending_view, name="pending"),
    path("nuevo/destinatarios/", view.recipients_view, name="recipients"),
    path("editor/", view.editor_view, name="editor"),
    path("revisar/", view.review_view, name="review"),
    path("contrato-servicios-2026/", view.document_detail_view, name="detail"),
]

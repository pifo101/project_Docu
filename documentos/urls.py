from django.urls import path

from . import view


app_name = "documentos"

urlpatterns = [
    path("editor/", view.editor_view, name="editor"),
]

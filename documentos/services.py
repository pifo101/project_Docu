from django.db.models import Count, Q

from .models import DestinatarioDocumento, Documento, EnvioDocumento


PENDING_RECIPIENT_STATES = (
    DestinatarioDocumento.Estado.PENDIENTE,
    DestinatarioDocumento.Estado.VISTO,
)


def sender_documents_context(user):
    documents = (
        Documento.objects.filter(propietario=user)
        .select_related("envio")
        .prefetch_related("envio__destinatarios")
    )
    return {
        "owned_documents": documents,
        "owned_document_count": documents.count(),
        "sent_document_count": documents.filter(
            envio__estado=EnvioDocumento.Estado.ENVIADO,
        ).count(),
        "waiting_signature_count": DestinatarioDocumento.objects.filter(
            envio__remitente=user,
            envio__estado=EnvioDocumento.Estado.ENVIADO,
            estado__in=PENDING_RECIPIENT_STATES,
        ).count(),
        "recipient_pending_count": recipient_documents_queryset(user).filter(
            estado__in=PENDING_RECIPIENT_STATES,
        ).count(),
    }


def recipient_documents_queryset(user):
    return (
        DestinatarioDocumento.objects.filter(
            usuario=user,
            envio__estado=EnvioDocumento.Estado.ENVIADO,
        )
        .select_related("envio__documento", "envio__remitente")
        .order_by("-envio__fecha_envio", "-fecha_agregado")
    )


def recipient_documents_context(user, selected_status="todos"):
    if selected_status not in {"todos", "pendientes", "completados"}:
        selected_status = "todos"

    queryset = recipient_documents_queryset(user)
    counts = queryset.aggregate(
        document_count=Count("pk"),
        pending_count=Count(
            "pk",
            filter=Q(estado__in=PENDING_RECIPIENT_STATES),
        ),
        completed_count=Count(
            "pk",
            filter=Q(estado=DestinatarioDocumento.Estado.FIRMADO),
        ),
    )

    if selected_status == "pendientes":
        documents = queryset.filter(estado__in=PENDING_RECIPIENT_STATES)
    elif selected_status == "completados":
        documents = queryset.filter(estado=DestinatarioDocumento.Estado.FIRMADO)
    else:
        documents = queryset

    return {
        "documents": documents,
        "selected_status": selected_status,
        **counts,
    }

from django.db.models import Count, Q

from .models import DestinatarioDocumento, Documento, EnvioDocumento


PENDING_RECIPIENT_STATES = (
    DestinatarioDocumento.Estado.PENDIENTE,
    DestinatarioDocumento.Estado.VISTO,
)

RECIPIENT_STATUS_PRESENTATION = {
    DestinatarioDocumento.Estado.BORRADOR: ("Borrador", "draft", "○"),
    DestinatarioDocumento.Estado.PENDIENTE: ("Pendiente", "pending", "○"),
    DestinatarioDocumento.Estado.VISTO: ("Visto", "viewed", "◉"),
    DestinatarioDocumento.Estado.FIRMADO: ("Firmado", "complete", "✓"),
}


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


def document_tracking_context(document):
    try:
        envio = document.envio
    except EnvioDocumento.DoesNotExist:
        envio = None

    if envio is None:
        return {
            "envio": None,
            "tracking_recipients": [],
            "signature_total": 0,
            "signature_completed": 0,
            "signature_pending": 0,
            "signature_percentage": 0,
            "all_signed": False,
            "activity_events": [],
            "last_activity": None,
            "signed_document_download_url": None,
        }

    recipients = list(envio.destinatarios.all())
    tracking_recipients = []
    activity_events = []

    if envio.estado == EnvioDocumento.Estado.ENVIADO and envio.fecha_envio:
        activity_events.append({
            "occurred_at": envio.fecha_envio,
            "description": "Documento enviado",
            "kind": "sent",
            "order": 0,
        })

    for recipient in recipients:
        signature = getattr(recipient, "firma", None)
        label, status_class, symbol = RECIPIENT_STATUS_PRESENTATION.get(
            recipient.estado,
            (recipient.get_estado_display(), "draft", "○"),
        )
        tracking_recipients.append({
            "recipient": recipient,
            "signature": signature,
            "label": label,
            "status_class": status_class,
            "symbol": symbol,
        })

        if recipient.fecha_visualizacion:
            activity_events.append({
                "occurred_at": recipient.fecha_visualizacion,
                "description": f"{recipient.usuario} visualizó el documento",
                "kind": "viewed",
                "order": 1,
            })
        if signature is not None and signature.fecha_firma:
            activity_events.append({
                "occurred_at": signature.fecha_firma,
                "description": f"{recipient.usuario} firmó el documento",
                "kind": "signed",
                "order": 2,
            })

    activity_events.sort(key=lambda event: (event["occurred_at"], event["order"]))
    total = len(recipients)
    completed = sum(
        recipient.estado == DestinatarioDocumento.Estado.FIRMADO
        for recipient in recipients
    )

    return {
        "envio": envio,
        "tracking_recipients": tracking_recipients,
        "signature_total": total,
        "signature_completed": completed,
        "signature_pending": total - completed,
        "signature_percentage": round(completed * 100 / total) if total else 0,
        "all_signed": total > 0 and completed == total,
        "activity_events": activity_events,
        "last_activity": activity_events[-1] if activity_events else None,
        # La rama que genere el PDF podrá reemplazar este valor por su URL real.
        "signed_document_download_url": None,
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

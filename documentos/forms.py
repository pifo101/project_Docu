from django import forms

from usuarios.models import Usuario

from .models import Documento


class DocumentoForm(forms.ModelForm):
    class Meta:
        model = Documento
        fields = ("archivo", "descripcion")
        labels = {"archivo": "Archivo PDF", "descripcion": "Descripción o comentario"}
        help_texts = {"descripcion": "Opcional. Máximo 1000 caracteres."}
        widgets = {"descripcion": forms.Textarea(attrs={"rows": 3})}


class SeleccionDestinatariosForm(forms.Form):
    class Modo:
        UNA_PERSONA = "single"
        COMITE = "committee"
        PERSONAS = "people"

    recipient_mode = forms.ChoiceField(choices=(
        (Modo.UNA_PERSONA, "Una persona"),
        (Modo.COMITE, "Comité completo"),
        (Modo.PERSONAS, "Personas específicas"),
    ))
    recipients = forms.ModelMultipleChoiceField(
        queryset=Usuario.objects.none(),
        required=False,
    )

    def __init__(self, *args, usuarios_disponibles, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["recipients"].queryset = usuarios_disponibles

    def clean(self):
        cleaned_data = super().clean()
        modo = cleaned_data.get("recipient_mode")
        destinatarios = cleaned_data.get("recipients")
        if modo == self.Modo.COMITE or destinatarios is None:
            return cleaned_data

        cantidad = destinatarios.count()
        if modo == self.Modo.UNA_PERSONA and cantidad != 1:
            self.add_error("recipients", "Selecciona exactamente una persona válida.")
        elif modo == self.Modo.PERSONAS and cantidad < 1:
            self.add_error("recipients", "Selecciona al menos una persona válida.")
        return cleaned_data

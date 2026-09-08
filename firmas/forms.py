import base64
import binascii

from django.conf import settings
from django import forms
from django.core.exceptions import ValidationError

from .models import Firma
from .validators import validate_canvas_png, validate_uploaded_signature

FIRMA_MAX_BYTES = 1024 * 1024


class FirmaForm(forms.Form):
    metodo = forms.ChoiceField(choices=Firma.Metodo.choices)
    firma = forms.CharField(required=False)
    consentimiento = forms.BooleanField(required=True)

    def clean_firma(self):
        data_url = self.cleaned_data.get("firma", "")
        if self.data.get("metodo") != Firma.Metodo.DIBUJADA:
            return None
        prefix = "data:image/png;base64,"
        if not data_url.startswith(prefix):
            raise forms.ValidationError("La firma debe ser una imagen PNG válida.")

        encoded = data_url[len(prefix):]
        if not encoded:
            raise forms.ValidationError("Dibuja tu firma antes de continuar.")
        if len(encoded) > ((FIRMA_MAX_BYTES + 2) // 3) * 4:
            raise forms.ValidationError("La imagen de la firma excede el tamaño permitido.")

        try:
            image = base64.b64decode(encoded, validate=True)
        except (binascii.Error, ValueError):
            raise forms.ValidationError("La firma contiene datos base64 inválidos.")

        if not image:
            raise forms.ValidationError("Dibuja tu firma antes de continuar.")
        if len(image) > FIRMA_MAX_BYTES:
            raise forms.ValidationError("La imagen de la firma excede el tamaño permitido.")
        try:
            validate_canvas_png(image)
        except ValidationError as error:
            raise forms.ValidationError(error.messages)
        return image


class FirmaPerfilForm(forms.Form):
    imagen = forms.FileField()

    def clean_imagen(self):
        uploaded = self.cleaned_data["imagen"]
        max_size = settings.FIRMA_PERFIL_MAX_FILE_SIZE
        if not uploaded.size:
            raise forms.ValidationError("El archivo de firma no puede estar vacío.")
        if uploaded.size > max_size:
            raise forms.ValidationError("La firma guardada excede el tamaño permitido.")

        image = uploaded.read()
        uploaded.seek(0)
        try:
            image_format = validate_uploaded_signature(image, uploaded.name)
        except ValidationError as error:
            raise forms.ValidationError(error.messages)
        self.image_bytes = image
        self.image_format = image_format
        return uploaded

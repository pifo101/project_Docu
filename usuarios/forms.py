from django import forms
from django.contrib.auth import authenticate, password_validation
from django.contrib.auth.forms import UserChangeForm
from django.core.exceptions import ValidationError

from .models import (
    Usuario,
    normalize_institutional_email,
    validate_institutional_email,
)


class RegistroUsuarioForm(forms.ModelForm):
    first_name = forms.CharField(
        label="Nombres",
        max_length=150,
        widget=forms.TextInput(attrs={"autocomplete": "given-name"}),
    )
    last_name = forms.CharField(
        label="Apellidos",
        max_length=150,
        widget=forms.TextInput(attrs={"autocomplete": "family-name"}),
    )
    password1 = forms.CharField(
        label="Contraseña",
        help_text=password_validation.password_validators_help_text_html(),
        strip=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
    )
    password2 = forms.CharField(
        label="Confirmación de contraseña",
        strip=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
    )

    class Meta:
        model = Usuario
        fields = ("first_name", "last_name", "email", "comite", "cargo")
        labels = {
            "email": "Correo institucional",
            "comite": "Comité",
            "cargo": "Cargo",
        }
        widgets = {
            "email": forms.EmailInput(attrs={"autocomplete": "email"}),
        }

    def clean_email(self):
        email = normalize_institutional_email(self.cleaned_data["email"])
        validate_institutional_email(email)
        if Usuario.objects.filter(email__iexact=email).exists():
            raise ValidationError(
                "Ya existe un usuario con este correo electrónico.",
                code="duplicate_email",
            )
        return email

    def clean(self):
        cleaned_data = super().clean()
        password1 = cleaned_data.get("password1")
        password2 = cleaned_data.get("password2")

        if password1 and password2 and password1 != password2:
            self.add_error("password2", "Las contraseñas no coinciden.")

        return cleaned_data

    def _post_clean(self):
        super()._post_clean()
        password1 = self.cleaned_data.get("password1")

        if password1:
            try:
                password_validation.validate_password(password1, self.instance)
            except ValidationError as error:
                self.add_error("password1", error)

    def save(self, commit=True):
        user = super().save(commit=False)
        user.set_password(self.cleaned_data["password1"])
        if commit:
            user.save()
            self.save_m2m()
        return user


class LoginUsuarioForm(forms.Form):
    email = forms.EmailField(label="Correo institucional")
    password = forms.CharField(
        label="Contraseña",
        strip=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "current-password"}),
    )

    def __init__(self, request=None, *args, **kwargs):
        self.request = request
        self.user_cache = None
        super().__init__(*args, **kwargs)

    def clean(self):
        cleaned_data = super().clean()
        email = cleaned_data.get("email")
        password = cleaned_data.get("password")

        if email and password:
            email = normalize_institutional_email(email)
            cleaned_data["email"] = email
            self.user_cache = authenticate(
                self.request,
                email=email,
                password=password,
            )
            if self.user_cache is None:
                raise ValidationError(
                    "Correo o contraseña incorrectos.",
                    code="invalid_login",
                )

        return cleaned_data

    def get_user(self):
        return self.user_cache


class UsuarioAdminChangeForm(UserChangeForm):
    class Meta(UserChangeForm.Meta):
        model = Usuario
        fields = "__all__"

from django import forms
from django.contrib.auth import authenticate, password_validation
from django.contrib.auth.forms import UserChangeForm
from django.core.exceptions import ValidationError
from django.db.models import Q

from .constants import OFFICIAL_COMMITTEE_NAMES
from .models import (
    Cargo,
    Comite,
    Usuario,
    normalize_institutional_email,
    validate_institutional_email,
)


ORGANIZATIONAL_CONSTRAINTS = {
    "un_presidente_por_comite",
    "un_vicepresidente_por_comite",
    "un_secretario_por_comite",
    "un_tesorero_por_comite",
}


def es_conflicto_integridad_organizacional(error):
    diagnostico = getattr(error.__cause__, "diag", None)
    return getattr(diagnostico, "constraint_name", None) in ORGANIZATIONAL_CONSTRAINTS


def comites_oficiales():
    return Comite.objects.filter(
        activo=True,
        nombre__in=OFFICIAL_COMMITTEE_NAMES,
    )


def mensaje_conflicto_organizacional(cargo):
    nombre = dict(Cargo.Codigo.choices).get(cargo.codigo, cargo.nombre).lower()
    return f"El comité seleccionado ya tiene un {nombre}."


def conflicto_organizacional(comite, cargo, *, excluir_usuario=None):
    if not comite or not cargo or cargo.codigo == Cargo.Codigo.MIEMBRO:
        return None
    usuarios = Usuario.objects.filter(comite=comite, cargo=cargo)
    if excluir_usuario:
        usuarios = usuarios.exclude(pk=excluir_usuario)
    return mensaje_conflicto_organizacional(cargo) if usuarios.exists() else None


def validar_asignacion_organizacional(form, cleaned_data):
    comite = cleaned_data.get("comite")
    cargo = cleaned_data.get("cargo")
    mensaje = conflicto_organizacional(
        comite,
        cargo,
        excluir_usuario=form.instance.pk,
    )
    if mensaje:
        form.add_error("cargo", mensaje)


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

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["comite"].queryset = comites_oficiales()
        self.fields["cargo"].queryset = Cargo.objects.filter(
            codigo__in=Cargo.Codigo.values,
        )

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

        validar_asignacion_organizacional(self, cleaned_data)

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


class RegistroPublicoUsuarioForm(RegistroUsuarioForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)


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

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        comites = Comite.objects.filter(nombre__in=OFFICIAL_COMMITTEE_NAMES).filter(
            Q(activo=True) | Q(pk=self.instance.comite_id)
        )
        if "comite" in self.fields:
            self.fields["comite"].queryset = comites
        if "cargo" in self.fields:
            self.fields["cargo"].queryset = Cargo.objects.filter(
                codigo__in=Cargo.Codigo.values,
            )

    def clean(self):
        cleaned_data = super().clean()
        validar_asignacion_organizacional(self, cleaned_data)
        return cleaned_data

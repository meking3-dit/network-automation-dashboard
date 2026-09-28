import hmac

from django import forms
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import UserCreationForm

from .models import CommandTemplate, Credential, Device, DeviceGroup, Job

User = get_user_model()


class RegistrationForm(UserCreationForm):
    email = forms.EmailField(help_text="Used for account recovery and security notices.")
    registration_code = forms.CharField(
        strip=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "one-time-code"}),
        help_text="Get this code from your NetOps administrator.",
    )

    class Meta(UserCreationForm.Meta):
        model = User
        fields = ("username", "email")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.setdefault("class", "form-control")

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("An account already uses this email address.")
        return email

    def clean_registration_code(self):
        submitted = self.cleaned_data["registration_code"]
        expected = settings.REGISTRATION_CODE
        if not expected:
            raise forms.ValidationError("Registration is not configured. Contact an administrator.")
        if not hmac.compare_digest(submitted, expected):
            raise forms.ValidationError("The registration code is invalid.")
        return submitted

    def save(self, commit=True):
        user = super().save(commit=False)
        user.email = self.cleaned_data["email"]
        if commit:
            user.save()
        return user


class StyledModelForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.setdefault("class", "form-control")


class DeviceForm(StyledModelForm):
    class Meta:
        model = Device
        fields = ["name", "host", "device_type", "port", "credential", "groups", "enabled"]
        widgets = {"groups": forms.CheckboxSelectMultiple()}


class DeviceGroupForm(StyledModelForm):
    class Meta:
        model = DeviceGroup
        fields = ["name", "description"]


class CredentialForm(StyledModelForm):
    password = forms.CharField(widget=forms.PasswordInput(render_value=True))
    secret = forms.CharField(required=False, widget=forms.PasswordInput(render_value=True), help_text="Optional enable secret")

    class Meta:
        model = Credential
        fields = ["name", "username", "password", "secret"]


class CommandTemplateForm(StyledModelForm):
    class Meta:
        model = CommandTemplate
        fields = ["name", "kind", "commands", "description"]
        widgets = {"commands": forms.Textarea(attrs={"rows": 8, "class": "code-input"})}


class JobForm(forms.ModelForm):
    groups = forms.ModelMultipleChoiceField(
        queryset=DeviceGroup.objects.all(), required=False, widget=forms.CheckboxSelectMultiple
    )
    template = forms.ModelChoiceField(queryset=CommandTemplate.objects.all(), required=False)

    class Meta:
        model = Job
        fields = ["name", "kind", "devices", "groups", "template", "commands", "pre_commands", "post_commands"]
        widgets = {
            "devices": forms.CheckboxSelectMultiple,
            "commands": forms.Textarea(attrs={"rows": 8, "placeholder": "One command per line"}),
            "pre_commands": forms.Textarea(attrs={"rows": 4, "placeholder": "Optional show commands before the change"}),
            "post_commands": forms.Textarea(attrs={"rows": 4, "placeholder": "Optional show commands after the change"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["devices"].queryset = Device.objects.filter(enabled=True)
        for field in self.fields.values():
            field.widget.attrs.setdefault("class", "form-control")

    def clean(self):
        cleaned = super().clean()
        devices = cleaned.get("devices")
        groups = cleaned.get("groups")
        if not devices and not groups:
            raise forms.ValidationError("Select at least one device or device group.")
        kind = cleaned.get("kind")
        template = cleaned.get("template")
        commands = cleaned.get("commands", "").strip()
        if template and not commands:
            commands = template.commands
            cleaned["commands"] = commands
        if kind == Job.Kind.BACKUP and not commands:
            cleaned["commands"] = "show running-config"
        elif kind not in (Job.Kind.TEST,) and not commands:
            self.add_error("commands", "Enter commands or select a command template.")
        return cleaned

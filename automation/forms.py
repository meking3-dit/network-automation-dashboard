from django import forms

from .models import CommandTemplate, Credential, Device, DeviceGroup, Job


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

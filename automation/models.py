from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import models

from .fields import EncryptedTextField

User = get_user_model()


class TimestampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class DeviceGroup(TimestampedModel):
    name = models.CharField(max_length=120, unique=True)
    description = models.TextField(blank=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class Credential(TimestampedModel):
    name = models.CharField(max_length=120, unique=True)
    username = models.CharField(max_length=150)
    password = EncryptedTextField()
    secret = EncryptedTextField(blank=True, help_text="Optional enable secret")

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class Device(TimestampedModel):
    name = models.CharField(max_length=120, unique=True)
    host = models.CharField(max_length=255, help_text="IP address or resolvable hostname")
    device_type = models.CharField(max_length=80, default="cisco_ios", help_text="Netmiko device_type")
    port = models.PositiveIntegerField(default=22)
    credential = models.ForeignKey(Credential, on_delete=models.PROTECT, related_name="devices")
    groups = models.ManyToManyField(DeviceGroup, blank=True, related_name="devices")
    use_jump_server = models.BooleanField(default=False, help_text="Connect to this device through a jump server")
    jump_host = models.CharField(max_length=255, blank=True, help_text="Jump server IP address or hostname")
    jump_port = models.PositiveIntegerField(default=22)
    jump_credential = models.ForeignKey(
        Credential, on_delete=models.PROTECT, null=True, blank=True, related_name="jump_devices",
        help_text="Credential used to log in to the jump server",
    )
    enabled = models.BooleanField(default=True)
    last_seen = models.DateTimeField(null=True, blank=True)
    last_error = models.TextField(blank=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name

    def clean(self):
        super().clean()
        if self.use_jump_server:
            errors = {}
            if not self.jump_host:
                errors["jump_host"] = "Jump host is required when using a jump server."
            if not self.jump_credential_id:
                errors["jump_credential"] = "Jump credential is required when using a jump server."
            if errors:
                raise ValidationError(errors)

    def connection_params(self):
        return {
            "device_type": self.device_type,
            "host": self.host,
            "port": self.port,
            "username": self.credential.username,
            "password": self.credential.password,
            "secret": self.credential.secret,
        }


class CommandTemplate(TimestampedModel):
    class Kind(models.TextChoices):
        SHOW = "show", "Show commands"
        CONFIG = "config", "Configuration commands"
        VALIDATION = "validation", "Validation commands"
        BACKUP = "backup", "Backup command"

    name = models.CharField(max_length=160, unique=True)
    kind = models.CharField(max_length=20, choices=Kind.choices)
    commands = models.TextField(help_text="One command per line")
    description = models.TextField(blank=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class Job(TimestampedModel):
    class Kind(models.TextChoices):
        TEST = "test", "Connectivity test"
        SHOW = "show", "Show commands"
        CONFIG = "config", "Configuration change"
        BACKUP = "backup", "Configuration backup"

    class Status(models.TextChoices):
        QUEUED = "queued", "Queued"
        RUNNING = "running", "Running"
        SUCCESS = "success", "Success"
        PARTIAL = "partial", "Partial"
        FAILED = "failed", "Failed"

    name = models.CharField(max_length=180)
    kind = models.CharField(max_length=20, choices=Kind.choices)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.QUEUED)
    devices = models.ManyToManyField(Device, related_name="jobs")
    commands = models.TextField(blank=True)
    pre_commands = models.TextField(blank=True)
    post_commands = models.TextField(blank=True)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name="automation_jobs")
    celery_task_id = models.CharField(max_length=255, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.name


class JobResult(models.Model):
    job = models.ForeignKey(Job, on_delete=models.CASCADE, related_name="results")
    device = models.ForeignKey(Device, on_delete=models.CASCADE, related_name="job_results")
    status = models.CharField(max_length=20, choices=Job.Status.choices, default=Job.Status.QUEUED)
    output = models.TextField(blank=True)
    error = models.TextField(blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["device__name"]
        constraints = [models.UniqueConstraint(fields=["job", "device"], name="unique_job_device_result")]


class CommandLog(models.Model):
    result = models.ForeignKey(JobResult, on_delete=models.CASCADE, related_name="logs")
    phase = models.CharField(max_length=20, default="execute")
    command = models.TextField()
    output = models.TextField(blank=True)
    success = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]


class ConfigurationBackup(models.Model):
    device = models.ForeignKey(Device, on_delete=models.CASCADE, related_name="backups")
    job = models.ForeignKey(Job, on_delete=models.SET_NULL, null=True, related_name="backups")
    content = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

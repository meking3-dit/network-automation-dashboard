from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase
from django.urls import reverse

from .forms import JobForm
from .models import CommandLog, CommandTemplate, ConfigurationBackup, Credential, Device, Job
from .tasks import execute_job


class AutomationTestCase(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("operator", password="test-pass-123")
        self.credential = Credential.objects.create(
            name="Lab SSH", username="admin", password="sensitive-password", secret="enable-secret"
        )
        self.device = Device.objects.create(name="core-01", host="192.0.2.10", credential=self.credential)

    def test_credentials_are_encrypted_in_database(self):
        with connection.cursor() as cursor:
            cursor.execute("SELECT password, secret FROM automation_credential WHERE id = %s", [self.credential.pk])
            password, secret = cursor.fetchone()
        self.assertTrue(password.startswith("enc::"))
        self.assertNotIn("sensitive-password", password)
        self.assertTrue(secret.startswith("enc::"))
        self.credential.refresh_from_db()
        self.assertEqual(self.credential.password, "sensitive-password")

    def test_dashboard_requires_login(self):
        response = self.client.get(reverse("dashboard"))
        self.assertRedirects(response, f"{reverse('login')}?next=/")
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(reverse("dashboard")).status_code, 200)

    def test_operator_pages_render(self):
        self.client.force_login(self.user)
        route_names = [
            "device-list", "device-add", "group-list", "group-add",
            "credential-list", "credential-add", "template-list", "template-add",
            "job-create", "job-list", "backup-list",
        ]
        for route_name in route_names:
            with self.subTest(route=route_name):
                self.assertEqual(self.client.get(reverse(route_name)).status_code, 200)

    def test_template_populates_commands_in_job_form(self):
        template = CommandTemplate.objects.create(name="Health", kind="show", commands="show version")
        form = JobForm(data={"name": "Health check", "kind": "show", "devices": [self.device.pk], "template": template.pk, "commands": ""})
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["commands"], "show version")

    @patch("automation.services.ConnectHandler")
    def test_show_job_records_output_and_command_log(self, connect_handler):
        connection = MagicMock()
        connection.send_command.return_value = "Cisco IOS XE Software"
        connect_handler.return_value = connection
        job = Job.objects.create(name="Collect facts", kind=Job.Kind.SHOW, commands="show version", created_by=self.user)
        job.devices.add(self.device)
        result = execute_job.apply(args=[job.pk]).get()
        job.refresh_from_db()
        self.assertEqual(result["status"], Job.Status.SUCCESS)
        self.assertEqual(job.status, Job.Status.SUCCESS)
        self.assertIn("Cisco IOS XE", job.results.get().output)
        self.assertEqual(CommandLog.objects.get().command, "show version")
        connection.disconnect.assert_called_once()

    @patch("automation.services.ConnectHandler")
    def test_config_job_runs_pre_and_post_validation(self, connect_handler):
        connection = MagicMock()
        connection.send_command.side_effect = ["before", "after"]
        connection.send_config_set.return_value = "configured"
        connect_handler.return_value = connection
        job = Job.objects.create(name="Change NTP", kind=Job.Kind.CONFIG, commands="ntp server 192.0.2.1", pre_commands="show clock", post_commands="show ntp associations", created_by=self.user)
        job.devices.add(self.device)
        execute_job.apply(args=[job.pk]).get()
        phases = list(CommandLog.objects.order_by("created_at").values_list("phase", flat=True))
        self.assertEqual(phases, ["pre", "configure", "post"])
        connection.send_config_set.assert_called_once_with(["ntp server 192.0.2.1"])

    @patch("automation.services.ConnectHandler")
    def test_backup_saves_raw_configuration(self, connect_handler):
        connection = MagicMock()
        connection.send_command.return_value = "hostname core-01\ninterface Loopback0"
        connect_handler.return_value = connection
        job = Job.objects.create(name="Nightly backup", kind=Job.Kind.BACKUP, commands="show running-config", created_by=self.user)
        job.devices.add(self.device)
        execute_job.apply(args=[job.pk]).get()
        backup = ConfigurationBackup.objects.get(job=job, device=self.device)
        self.assertEqual(backup.content, "hostname core-01\ninterface Loopback0")

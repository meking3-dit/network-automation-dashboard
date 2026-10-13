from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.core import mail
from django.core.exceptions import ValidationError
from django.db import connection
from django.test import TestCase, override_settings
from django.urls import reverse

from .forms import JobForm
from .models import CommandLog, CommandTemplate, ConfigurationBackup, Credential, Device, Job
from .services import netmiko_connection
from .tasks import execute_job


class AutomationTestCase(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            "operator", email="operator@example.com", password="test-pass-123"
        )
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

    @override_settings(REGISTRATION_CODE="private-invite-code")
    def test_registration_requires_the_configured_code(self):
        registration_data = {
            "username": "new-operator",
            "email": "new-operator@example.com",
            "password1": "Secure-registration-password-789!",
            "password2": "Secure-registration-password-789!",
            "registration_code": "wrong-code",
        }
        response = self.client.post(reverse("register"), registration_data)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "registration code is invalid")
        self.assertFalse(get_user_model().objects.filter(username="new-operator").exists())

        registration_data["registration_code"] = "private-invite-code"
        response = self.client.post(reverse("register"), registration_data)
        self.assertRedirects(response, reverse("login"))
        new_user = get_user_model().objects.get(username="new-operator")
        self.assertEqual(new_user.email, "new-operator@example.com")
        self.assertTrue(new_user.check_password("Secure-registration-password-789!"))

    @override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
    def test_forgotten_password_can_be_reset_from_email_link(self):
        response = self.client.post(
            reverse("password_reset"), {"email": self.user.email}
        )
        self.assertRedirects(response, reverse("password_reset_done"))
        self.assertEqual(len(mail.outbox), 1)

        reset_path = next(
            line.split("testserver", 1)[1]
            for line in mail.outbox[0].body.splitlines()
            if "testserver/accounts/reset/" in line
        )
        response = self.client.get(reset_path)
        self.assertEqual(response.status_code, 302)
        set_password_path = response["Location"]
        response = self.client.post(
            set_password_path,
            {
                "new_password1": "New-secure-password-456!",
                "new_password2": "New-secure-password-456!",
            },
        )
        self.assertRedirects(response, reverse("password_reset_complete"))
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("New-secure-password-456!"))

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

    @patch("automation.services.paramiko.SSHClient")
    @patch("automation.services.ConnectHandler")
    def test_jump_server_tunnel_is_used_when_enabled(self, connect_handler, ssh_client):
        jump_cred = Credential.objects.create(name="jump", username="jumpuser", password="jp")
        self.device.use_jump_server = True
        self.device.jump_host = "198.51.100.1"
        self.device.jump_credential = jump_cred
        self.device.save()
        client = ssh_client.return_value
        channel = client.get_transport.return_value.open_channel.return_value
        with netmiko_connection(self.device):
            pass
        client.connect.assert_called_once()
        self.assertEqual(client.connect.call_args.kwargs["username"], "jumpuser")
        self.assertIs(connect_handler.call_args.kwargs["sock"], channel)
        client.close.assert_called_once()

    def test_jump_server_requires_host_and_credential(self):
        self.device.use_jump_server = True
        with self.assertRaises(ValidationError):
            self.device.full_clean()

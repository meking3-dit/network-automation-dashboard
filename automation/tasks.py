from celery import shared_task
from django.utils import timezone

from .models import CommandLog, ConfigurationBackup, Job, JobResult
from .services import netmiko_connection, parse_commands


def _run_show(connection, result, commands, phase="execute"):
    blocks = []
    for command in commands:
        try:
            output = connection.send_command(command)
            CommandLog.objects.create(result=result, phase=phase, command=command, output=output)
            blocks.append(f"$ {command}\n{output}")
        except Exception as exc:
            CommandLog.objects.create(result=result, phase=phase, command=command, output=str(exc), success=False)
            raise
    return "\n\n".join(blocks)


def _execute_for_device(job, result):
    device = result.device
    sections = []
    with netmiko_connection(device) as connection:
        if job.kind == Job.Kind.TEST:
            prompt = connection.find_prompt()
            CommandLog.objects.create(result=result, phase="connect", command="find_prompt", output=prompt)
            return f"Connected successfully\nPrompt: {prompt}"

        pre = parse_commands(job.pre_commands)
        if pre:
            sections.append("=== PRE-CHANGE VALIDATION ===\n" + _run_show(connection, result, pre, "pre"))

        commands = parse_commands(job.commands)
        if job.kind == Job.Kind.CONFIG:
            output = connection.send_config_set(commands)
            CommandLog.objects.create(
                result=result, phase="configure", command="\n".join(commands), output=output
            )
            sections.append("=== CONFIGURATION ===\n" + output)
        else:
            if job.kind == Job.Kind.BACKUP:
                command = commands[0]
                output = connection.send_command(command)
                CommandLog.objects.create(result=result, phase="backup", command=command, output=output)
                ConfigurationBackup.objects.create(device=device, job=job, content=output)
                sections.append(f"$ {command}\n{output}")
            else:
                output = _run_show(connection, result, commands)
                sections.append(output)

        post = parse_commands(job.post_commands)
        if post:
            sections.append("=== POST-CHANGE VALIDATION ===\n" + _run_show(connection, result, post, "post"))
    return "\n\n".join(sections)


@shared_task(bind=True)
def execute_job(self, job_id):
    job = Job.objects.prefetch_related("devices__credential").get(pk=job_id)
    job.status = Job.Status.RUNNING
    job.started_at = timezone.now()
    job.celery_task_id = self.request.id or job.celery_task_id
    job.save(update_fields=["status", "started_at", "celery_task_id", "updated_at"])
    success_count = 0
    devices = list(job.devices.filter(enabled=True))

    for device in devices:
        result, _ = JobResult.objects.get_or_create(job=job, device=device)
        result.status = Job.Status.RUNNING
        result.started_at = timezone.now()
        result.save(update_fields=["status", "started_at"])
        try:
            result.output = _execute_for_device(job, result)
            result.status = Job.Status.SUCCESS
            result.error = ""
            success_count += 1
            device.last_seen = timezone.now()
            device.last_error = ""
        except Exception as exc:
            result.status = Job.Status.FAILED
            result.error = str(exc)
            device.last_error = str(exc)
        finally:
            result.finished_at = timezone.now()
            result.save(update_fields=["status", "output", "error", "finished_at"])
            device.save(update_fields=["last_seen", "last_error", "updated_at"])

    if not devices or success_count == 0:
        job.status = Job.Status.FAILED
    elif success_count == len(devices):
        job.status = Job.Status.SUCCESS
    else:
        job.status = Job.Status.PARTIAL
    job.finished_at = timezone.now()
    job.save(update_fields=["status", "finished_at", "updated_at"])
    return {"job_id": job.pk, "status": job.status, "success_count": success_count}

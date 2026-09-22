from django.contrib import admin

from .models import CommandLog, CommandTemplate, ConfigurationBackup, Credential, Device, DeviceGroup, Job, JobResult


@admin.register(Device)
class DeviceAdmin(admin.ModelAdmin):
    list_display = ("name", "host", "device_type", "credential", "enabled", "last_seen")
    list_filter = ("enabled", "device_type", "groups")
    search_fields = ("name", "host")


@admin.register(Job)
class JobAdmin(admin.ModelAdmin):
    list_display = ("name", "kind", "status", "created_by", "created_at", "finished_at")
    list_filter = ("kind", "status")
    readonly_fields = ("celery_task_id", "started_at", "finished_at")


admin.site.register(DeviceGroup)
admin.site.register(Credential)
admin.site.register(CommandTemplate)
admin.site.register(JobResult)
admin.site.register(CommandLog)
admin.site.register(ConfigurationBackup)

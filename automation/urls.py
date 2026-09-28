from django.urls import path

from . import views

urlpatterns = [
    path("accounts/register/", views.register, name="register"),
    path("", views.dashboard, name="dashboard"),
    path("devices/", views.DeviceList.as_view(), name="device-list"),
    path("devices/add/", views.DeviceCreate.as_view(), name="device-add"),
    path("devices/<int:pk>/edit/", views.DeviceUpdate.as_view(), name="device-edit"),
    path("devices/<int:pk>/delete/", views.DeviceDelete.as_view(), name="device-delete"),
    path("groups/", views.GroupList.as_view(), name="group-list"),
    path("groups/add/", views.GroupCreate.as_view(), name="group-add"),
    path("groups/<int:pk>/edit/", views.GroupUpdate.as_view(), name="group-edit"),
    path("groups/<int:pk>/delete/", views.GroupDelete.as_view(), name="group-delete"),
    path("credentials/", views.CredentialList.as_view(), name="credential-list"),
    path("credentials/add/", views.CredentialCreate.as_view(), name="credential-add"),
    path("credentials/<int:pk>/edit/", views.CredentialUpdate.as_view(), name="credential-edit"),
    path("credentials/<int:pk>/delete/", views.CredentialDelete.as_view(), name="credential-delete"),
    path("templates/", views.TemplateList.as_view(), name="template-list"),
    path("templates/add/", views.TemplateCreate.as_view(), name="template-add"),
    path("templates/<int:pk>/edit/", views.TemplateUpdate.as_view(), name="template-edit"),
    path("templates/<int:pk>/delete/", views.TemplateDelete.as_view(), name="template-delete"),
    path("execute/", views.job_create, name="job-create"),
    path("jobs/", views.JobList.as_view(), name="job-list"),
    path("jobs/<int:pk>/", views.job_detail, name="job-detail"),
    path("backups/", views.BackupList.as_view(), name="backup-list"),
    path("backups/<int:pk>/", views.backup_detail, name="backup-detail"),
    path("backups/<int:pk>/download/", views.backup_download, name="backup-download"),
]

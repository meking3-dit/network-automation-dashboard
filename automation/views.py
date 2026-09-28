from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.decorators import login_required
from django.db.models import Count, Q
from django.db.models.deletion import ProtectedError
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy
from django.views.generic import CreateView, DeleteView, ListView, UpdateView

from .forms import CommandTemplateForm, CredentialForm, DeviceForm, DeviceGroupForm, JobForm, RegistrationForm
from .models import CommandTemplate, ConfigurationBackup, Credential, Device, DeviceGroup, Job
from .tasks import execute_job


def register(request):
    if request.user.is_authenticated:
        return redirect("dashboard")
    if request.method == "POST":
        form = RegistrationForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "Account created. You can now sign in.")
            return redirect("login")
    else:
        form = RegistrationForm()
    return render(request, "registration/register.html", {"form": form})


@login_required
def dashboard(request):
    recent_jobs = Job.objects.select_related("created_by")[:6]
    context = {
        "device_count": Device.objects.count(),
        "online_count": Device.objects.filter(last_seen__isnull=False, last_error="").count(),
        "group_count": DeviceGroup.objects.count(),
        "job_count": Job.objects.count(),
        "failed_count": Job.objects.filter(status=Job.Status.FAILED).count(),
        "recent_jobs": recent_jobs,
        "recent_backups": ConfigurationBackup.objects.select_related("device")[:5],
        "nav": "dashboard",
    }
    return render(request, "automation/dashboard.html", context)


class SecureListView(LoginRequiredMixin, ListView):
    paginate_by = 25


class SecureCreateView(LoginRequiredMixin, CreateView):
    template_name = "automation/form.html"

    def form_valid(self, form):
        messages.success(self.request, f"{self.model._meta.verbose_name.title()} created.")
        return super().form_valid(form)


class SecureUpdateView(LoginRequiredMixin, UpdateView):
    template_name = "automation/form.html"

    def form_valid(self, form):
        messages.success(self.request, f"{self.model._meta.verbose_name.title()} updated.")
        return super().form_valid(form)


class SecureDeleteView(LoginRequiredMixin, DeleteView):
    template_name = "automation/confirm_delete.html"

    def form_valid(self, form):
        label = str(self.object)
        try:
            response = super().form_valid(form)
        except ProtectedError:
            messages.error(self.request, f"{label} is still in use and cannot be deleted.")
            return redirect(self.success_url)
        messages.success(self.request, f"{label} deleted.")
        return response


class DeviceList(SecureListView):
    model = Device
    template_name = "automation/device_list.html"
    context_object_name = "devices"

    def get_queryset(self):
        query = self.request.GET.get("q", "")
        return Device.objects.select_related("credential").prefetch_related("groups").filter(
            Q(name__icontains=query) | Q(host__icontains=query) | Q(device_type__icontains=query)
        )


class DeviceCreate(SecureCreateView):
    model = Device
    form_class = DeviceForm
    success_url = reverse_lazy("device-list")
    extra_context = {"title": "Add device", "nav": "inventory"}


class DeviceUpdate(SecureUpdateView):
    model = Device
    form_class = DeviceForm
    success_url = reverse_lazy("device-list")
    extra_context = {"title": "Edit device", "nav": "inventory"}


class DeviceDelete(SecureDeleteView):
    model = Device
    success_url = reverse_lazy("device-list")


class GroupList(SecureListView):
    model = DeviceGroup
    template_name = "automation/group_list.html"
    context_object_name = "groups"

    def get_queryset(self):
        return DeviceGroup.objects.annotate(device_count=Count("devices")).order_by("name")


class GroupCreate(SecureCreateView):
    model = DeviceGroup
    form_class = DeviceGroupForm
    success_url = reverse_lazy("group-list")
    extra_context = {"title": "Add device group", "nav": "groups"}


class GroupUpdate(SecureUpdateView):
    model = DeviceGroup
    form_class = DeviceGroupForm
    success_url = reverse_lazy("group-list")
    extra_context = {"title": "Edit device group", "nav": "groups"}


class GroupDelete(SecureDeleteView):
    model = DeviceGroup
    success_url = reverse_lazy("group-list")


class CredentialList(SecureListView):
    model = Credential
    template_name = "automation/credential_list.html"
    context_object_name = "credentials"
    queryset = Credential.objects.annotate(device_count=Count("devices")).order_by("name")


class CredentialCreate(SecureCreateView):
    model = Credential
    form_class = CredentialForm
    success_url = reverse_lazy("credential-list")
    extra_context = {"title": "Add credential", "nav": "credentials"}


class CredentialUpdate(SecureUpdateView):
    model = Credential
    form_class = CredentialForm
    success_url = reverse_lazy("credential-list")
    extra_context = {"title": "Edit credential", "nav": "credentials"}


class CredentialDelete(SecureDeleteView):
    model = Credential
    success_url = reverse_lazy("credential-list")


class TemplateList(SecureListView):
    model = CommandTemplate
    template_name = "automation/template_list.html"
    context_object_name = "templates"


class TemplateCreate(SecureCreateView):
    model = CommandTemplate
    form_class = CommandTemplateForm
    success_url = reverse_lazy("template-list")
    extra_context = {"title": "Add command template", "nav": "templates"}


class TemplateUpdate(SecureUpdateView):
    model = CommandTemplate
    form_class = CommandTemplateForm
    success_url = reverse_lazy("template-list")
    extra_context = {"title": "Edit command template", "nav": "templates"}


class TemplateDelete(SecureDeleteView):
    model = CommandTemplate
    success_url = reverse_lazy("template-list")


@login_required
def job_create(request):
    if request.method == "POST":
        form = JobForm(request.POST)
        if form.is_valid():
            job = form.save(commit=False)
            job.created_by = request.user
            job.commands = form.cleaned_data["commands"]
            job.save()
            selected_ids = set(form.cleaned_data["devices"].values_list("id", flat=True))
            group_ids = form.cleaned_data["groups"].values_list("id", flat=True)
            selected_ids.update(Device.objects.filter(groups__id__in=group_ids, enabled=True).values_list("id", flat=True))
            job.devices.set(selected_ids)
            try:
                result = execute_job.delay(job.pk)
                job.celery_task_id = result.id or ""
                job.save(update_fields=["celery_task_id", "updated_at"])
                messages.success(request, f"Job queued for {len(selected_ids)} device(s).")
            except Exception as exc:
                job.status = Job.Status.FAILED
                job.save(update_fields=["status", "updated_at"])
                messages.error(request, f"Could not queue the job. Check Celery/Redis: {exc}")
            return redirect("job-detail", pk=job.pk)
    else:
        form = JobForm(initial={"kind": request.GET.get("kind", Job.Kind.SHOW)})
    return render(request, "automation/job_form.html", {"form": form, "nav": "execute"})


class JobList(SecureListView):
    model = Job
    template_name = "automation/job_list.html"
    context_object_name = "jobs"

    def get_queryset(self):
        return Job.objects.select_related("created_by").annotate(device_count=Count("devices")).order_by("-created_at")


@login_required
def job_detail(request, pk):
    job = get_object_or_404(Job.objects.select_related("created_by"), pk=pk)
    results = job.results.select_related("device").prefetch_related("logs")
    return render(request, "automation/job_detail.html", {"job": job, "results": results, "nav": "jobs"})


class BackupList(SecureListView):
    model = ConfigurationBackup
    template_name = "automation/backup_list.html"
    context_object_name = "backups"
    queryset = ConfigurationBackup.objects.select_related("device", "job")


@login_required
def backup_detail(request, pk):
    backup = get_object_or_404(ConfigurationBackup.objects.select_related("device", "job"), pk=pk)
    return render(request, "automation/backup_detail.html", {"backup": backup, "nav": "backups"})


@login_required
def backup_download(request, pk):
    backup = get_object_or_404(ConfigurationBackup.objects.select_related("device"), pk=pk)
    response = HttpResponse(backup.content, content_type="text/plain")
    stamp = backup.created_at.strftime("%Y%m%d-%H%M%S")
    response["Content-Disposition"] = f'attachment; filename="{backup.device.name}-{stamp}.cfg"'
    return response

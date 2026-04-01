"""Upload batch management views."""
from __future__ import annotations

import hashlib
import os
import uuid
from pathlib import Path

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.views.generic import DetailView, ListView, View

from apps.core.mixins import HtmxMixin
from apps.distributors.models import get_user_distributors
from .forms import ReprocessForm, UploadBatchForm
from .models import UploadBatch, ImportRow


class BatchListView(LoginRequiredMixin, ListView):
    model = UploadBatch
    template_name = "uploads/batch_list.html"
    context_object_name = "batches"
    paginate_by = 25

    def get_queryset(self):
        user = self.request.user
        qs = UploadBatch.objects.select_related("distributor", "uploaded_by")
        if not (user.is_admin or user.is_superuser):
            qs = qs.filter(distributor__in=get_user_distributors(user))
        status = self.request.GET.get("status", "")
        if status:
            qs = qs.filter(status=status)
        return qs.order_by("-created_at")

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["status_choices"] = UploadBatch.STATUS_CHOICES
        ctx["selected_status"] = self.request.GET.get("status", "")
        return ctx


class BatchUploadView(LoginRequiredMixin, View):
    template_name = "uploads/batch_upload.html"

    def get(self, request):
        from django.shortcuts import render
        form = UploadBatchForm(user=request.user)
        return render(request, self.template_name, {"form": form})

    def post(self, request):
        from django.shortcuts import render
        form = UploadBatchForm(request.POST, request.FILES, user=request.user)
        if not form.is_valid():
            return render(request, self.template_name, {"form": form})

        uploaded_file = form.cleaned_data["file"]
        distributor = form.cleaned_data["distributor"]

        # Save file to disk
        upload_dir = Path(settings.MEDIA_ROOT) / "uploads" / str(distributor.code)
        upload_dir.mkdir(parents=True, exist_ok=True)

        ext = Path(uploaded_file.name).suffix.lower()
        unique_name = f"{uuid.uuid4().hex}{ext}"
        dest_path = upload_dir / unique_name

        with open(dest_path, "wb") as f:
            for chunk in uploaded_file.chunks():
                f.write(chunk)

        # Compute checksum
        sha256 = hashlib.sha256()
        with open(dest_path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                sha256.update(chunk)
        checksum = sha256.hexdigest()

        # Check for duplicate file
        if UploadBatch.objects.filter(
            file_checksum=checksum,
            distributor=distributor,
            status=UploadBatch.STATUS_PROCESSED,
        ).exists():
            messages.warning(
                request,
                "A file with identical content has already been processed for this distributor. "
                "Proceeding with upload, but please verify.",
            )

        # Relative path from MEDIA_ROOT
        relative_path = str(dest_path.relative_to(settings.MEDIA_ROOT))

        batch = UploadBatch.objects.create(
            distributor=distributor,
            uploaded_by=request.user,
            original_filename=uploaded_file.name,
            file_path=relative_path,
            file_checksum=checksum,
            status=UploadBatch.STATUS_PENDING,
        )

        # Enqueue processing task
        from .tasks import process_upload_batch
        process_upload_batch.delay(batch.pk)

        messages.success(request, f"File '{uploaded_file.name}' uploaded. Processing started.")
        return redirect(reverse("uploads:batch_detail", kwargs={"pk": batch.pk}))


class BatchDetailView(LoginRequiredMixin, DetailView):
    model = UploadBatch
    template_name = "uploads/batch_detail.html"
    context_object_name = "batch"

    def get_queryset(self):
        user = self.request.user
        qs = UploadBatch.objects.select_related("distributor", "uploaded_by")
        if not (user.is_admin or user.is_superuser):
            qs = qs.filter(distributor__in=get_user_distributors(user))
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        run = self.object.get_latest_run()
        ctx["latest_run"] = run
        ctx["reprocess_form"] = ReprocessForm()
        if run:
            ctx["match_logs"] = run.match_logs.select_related("template_version__template")
        return ctx


class BatchStatusView(LoginRequiredMixin, HtmxMixin, View):
    """HTMX polling endpoint — returns partial with current batch status."""

    def get(self, request, pk):
        from django.shortcuts import render
        batch = get_object_or_404(UploadBatch, pk=pk)
        return render(request, "uploads/partials/_processing_status.html", {"batch": batch})


class BatchDeleteView(LoginRequiredMixin, View):
    """Delete an upload batch (admin only). Blocked while processing."""

    def post(self, request, pk):
        from apps.core.mixins import AdminRequiredMixin
        if not (request.user.is_admin or request.user.is_superuser):
            messages.error(request, "You do not have permission to delete batches.")
            return redirect(reverse("uploads:batch_list"))
        batch = get_object_or_404(UploadBatch, pk=pk)
        if batch.status == UploadBatch.STATUS_PROCESSING:
            messages.error(request, "Cannot delete a batch that is currently processing.")
            return redirect(reverse("uploads:batch_detail", kwargs={"pk": pk}))
        name = batch.original_filename
        batch.delete()
        messages.success(request, f"Batch '{name}' deleted.")
        return redirect(reverse("uploads:batch_list"))


class BatchReprocessView(LoginRequiredMixin, View):
    """Trigger reprocessing of a batch."""

    def post(self, request, pk):
        batch = get_object_or_404(UploadBatch, pk=pk)
        form = ReprocessForm(request.POST)
        if not form.is_valid():
            messages.error(request, "Please provide a reason for reprocessing.")
            return redirect(reverse("uploads:batch_detail", kwargs={"pk": pk}))

        if batch.status == UploadBatch.STATUS_PROCESSING:
            messages.warning(request, "Batch is currently being processed. Please wait.")
            return redirect(reverse("uploads:batch_detail", kwargs={"pk": pk}))

        from .tasks import reprocess_upload_batch
        reprocess_upload_batch.delay(
            batch.pk,
            form.cleaned_data["reason"],
            request.user.pk,
        )
        messages.success(request, "Reprocess queued.")
        return redirect(reverse("uploads:batch_detail", kwargs={"pk": pk}))

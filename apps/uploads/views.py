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
from django.shortcuts import get_object_or_404, redirect, render
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
        form = UploadBatchForm(user=request.user)
        return render(request, self.template_name, {"form": form})

    def post(self, request):
        form = UploadBatchForm(request.POST, request.FILES, user=request.user)
        if not form.is_valid():
            return render(request, self.template_name, {"form": form})

        uploaded_files = form.cleaned_data["files"]
        distributor = form.cleaned_data["distributor"]

        upload_dir = Path(settings.MEDIA_ROOT) / "uploads" / str(distributor.code)
        upload_dir.mkdir(parents=True, exist_ok=True)

        from .tasks import process_upload_batch
        created_batches = []
        duplicate_count = 0

        for uploaded_file in uploaded_files:
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

            # Check for duplicate
            if UploadBatch.objects.filter(
                file_checksum=checksum,
                distributor=distributor,
                status=UploadBatch.STATUS_PROCESSED,
            ).exists():
                duplicate_count += 1

            relative_path = str(dest_path.relative_to(settings.MEDIA_ROOT))

            batch = UploadBatch.objects.create(
                distributor=distributor,
                uploaded_by=request.user,
                original_filename=uploaded_file.name,
                file_path=relative_path,
                file_checksum=checksum,
                status=UploadBatch.STATUS_PENDING,
            )
            process_upload_batch.delay(batch.pk)
            created_batches.append(batch)

            # Activity log
            from apps.core.services import log_activity
            from apps.core.models import ActivityLog
            log_activity(
                user=request.user,
                action=ActivityLog.ACTION_UPLOAD,
                description=f"Uploaded file '{uploaded_file.name}' for {distributor.name}",
                target=batch,
                details={"filename": uploaded_file.name, "size": uploaded_file.size, "checksum": checksum},
                request=request,
            )

        # Build feedback message
        count = len(created_batches)
        if count == 1:
            messages.success(request, f"File '{created_batches[0].original_filename}' uploaded. Processing started.")
            if duplicate_count:
                messages.warning(request, "This file has been processed before. Proceeding anyway.")
            return redirect(reverse("uploads:batch_detail", kwargs={"pk": created_batches[0].pk}))
        else:
            messages.success(request, f"{count} files uploaded. Processing started.")
            if duplicate_count:
                messages.warning(request, f"{duplicate_count} file(s) appear to be duplicates of previously processed files.")
            return redirect(reverse("uploads:batch_list"))


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
        batch_pk = batch.pk
        batch.delete()
        from apps.core.services import log_activity
        from apps.core.models import ActivityLog
        log_activity(
            user=request.user,
            action=ActivityLog.ACTION_DELETE,
            description=f"Deleted upload batch '{name}'",
            details={"batch_id": batch_pk, "filename": name},
            request=request,
        )
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
        from apps.core.services import log_activity
        from apps.core.models import ActivityLog
        log_activity(
            user=request.user,
            action=ActivityLog.ACTION_REPROCESS,
            description=f"Reprocessed batch '{batch.original_filename}'",
            target=batch,
            details={"reason": form.cleaned_data["reason"]},
            request=request,
        )
        messages.success(request, "Reprocess queued.")
        return redirect(reverse("uploads:batch_detail", kwargs={"pk": pk}))


class BatchQuickReprocessView(LoginRequiredMixin, View):
    """Quick reprocess from batch list — no reason required."""

    def post(self, request, pk):
        batch = get_object_or_404(UploadBatch, pk=pk)
        if batch.status == UploadBatch.STATUS_PROCESSING:
            messages.warning(request, "Batch is currently being processed.")
            return redirect(reverse("uploads:batch_list"))

        from .tasks import reprocess_upload_batch
        reprocess_upload_batch.delay(batch.pk, "Quick reprocess", request.user.pk)

        from apps.core.services import log_activity
        from apps.core.models import ActivityLog
        log_activity(
            user=request.user,
            action=ActivityLog.ACTION_REPROCESS,
            description=f"Quick reprocessed '{batch.original_filename}'",
            target=batch,
            request=request,
        )
        messages.success(request, f"Reprocess queued for '{batch.original_filename}'.")
        return redirect(reverse("uploads:batch_list"))

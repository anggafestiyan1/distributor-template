"""Dashboard views — summary and recent activity."""
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import JsonResponse
from django.views.generic import TemplateView, View

from apps.distributors.models import Distributor, get_user_distributors
from apps.uploads.models import ImportRow, UploadBatch, ProcessingRun
from apps.master_data.models import MasterDataRecord


class DashboardView(LoginRequiredMixin, TemplateView):
    template_name = "dashboard/index.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        user = self.request.user
        distributors = get_user_distributors(user)

        # Upload stats — all statuses
        batches = UploadBatch.objects.filter(distributor__in=distributors)
        ctx["total_batches"] = batches.count()
        ctx["pending_batches"] = batches.filter(status=UploadBatch.STATUS_PENDING).count()
        ctx["processing_batches"] = batches.filter(status=UploadBatch.STATUS_PROCESSING).count()
        ctx["processed_batches"] = batches.filter(status=UploadBatch.STATUS_PROCESSED).count()
        ctx["error_batches"] = batches.filter(status=UploadBatch.STATUS_ERROR).count()
        ctx["mismatch_batches"] = batches.filter(status=UploadBatch.STATUS_MISMATCH).count()

        # Review stats
        runs_qs = ProcessingRun.objects.filter(batch__distributor__in=distributors)
        ctx["pending_review_runs"] = runs_qs.filter(
            batch__status=UploadBatch.STATUS_PROCESSED,
            import_rows__review_decision=ImportRow.DECISION_PENDING,
        ).distinct().count()
        ctx["total_approved_rows"] = ImportRow.objects.filter(
            processing_run__batch__distributor__in=distributors,
            review_decision=ImportRow.DECISION_APPROVED,
        ).count()
        ctx["total_rejected_rows"] = ImportRow.objects.filter(
            processing_run__batch__distributor__in=distributors,
            review_decision=ImportRow.DECISION_REJECTED,
        ).count()

        # Master data count
        ctx["master_record_count"] = MasterDataRecord.objects.filter(
            distributor__in=distributors
        ).count()

        # Admin-only counts
        if user.is_admin or user.is_superuser:
            ctx["total_distributors"] = Distributor.objects.filter(is_active=True).count()
            from django.contrib.auth import get_user_model
            ctx["total_users"] = get_user_model().objects.filter(is_active=True).count()

        # Recent uploads
        ctx["recent_batches"] = batches.select_related(
            "distributor", "uploaded_by"
        ).order_by("-created_at")[:10]

        # Recent reviews
        ctx["recent_runs"] = runs_qs.select_related(
            "batch__distributor", "template_version__template"
        ).order_by("-started_at")[:10]

        return ctx


class HealthCheckView(View):
    """Simple health check endpoint for Docker and load balancers."""

    def get(self, request):
        return JsonResponse({"status": "ok"})

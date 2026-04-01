"""Review workflow views — file-level and row-level."""
from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.generic import ListView, View

from apps.core.mixins import HtmxMixin, StaffOrAdminMixin
from apps.distributors.models import get_user_distributors
from apps.uploads.models import ImportRow, ProcessingRun, UploadBatch
from .models import ReviewAction


def _normalize_for_master(mapped_data: dict, standard_fields) -> dict:
    """Build a clean, ordered data dict for MasterDataRecord.data.

    Rules per standard field:
    - Only fields defined in StandardMasterField are included (no extra keys)
    - Values are cast to their declared data_type
    - Dates: strip time component ("2026-02-24 00:00:00" → "2026-02-24")
    - Missing fields → empty string
    - Field order follows StandardMasterField.order
    """
    from decimal import Decimal, InvalidOperation

    result = {}
    for sf in standard_fields:
        raw = str(mapped_data.get(sf.name, "")).strip()

        if not raw:
            result[sf.name] = ""
            continue

        if sf.data_type == "date":
            # Strip time component produced by Excel datetime parsing
            if " " in raw and ":" in raw:
                raw = raw.split(" ")[0]
            result[sf.name] = raw

        elif sf.data_type == "integer":
            try:
                result[sf.name] = int(raw.replace(",", "").replace(".", ""))
            except (ValueError, AttributeError):
                result[sf.name] = raw

        elif sf.data_type == "decimal":
            try:
                result[sf.name] = float(Decimal(raw.replace(",", ".")))
            except (InvalidOperation, ValueError, AttributeError):
                result[sf.name] = raw

        elif sf.data_type == "boolean":
            result[sf.name] = raw.lower() in ("true", "1", "yes", "y")

        else:
            result[sf.name] = raw

    return result


def _apply_row_decision(import_row: ImportRow, decision: str, note: str, user) -> None:
    """Apply a review decision to a row and create an audit ReviewAction."""
    import_row.review_decision = decision
    import_row.review_note = note
    import_row.reviewed_by = user
    import_row.reviewed_at = timezone.now()
    if decision == "approved":
        import_row.row_status = ImportRow.ROW_STATUS_APPROVED
    elif decision == "rejected":
        import_row.row_status = ImportRow.ROW_STATUS_REJECTED
    import_row.save(update_fields=[
        "review_decision", "review_note", "reviewed_by", "reviewed_at", "row_status"
    ])
    ReviewAction.objects.create(
        import_row=import_row,
        action=decision,
        actor=user,
        note=note,
    )


class ReviewQueueView(LoginRequiredMixin, StaffOrAdminMixin, ListView):
    """File-level review queue."""
    model = ProcessingRun
    template_name = "review/review_queue.html"
    context_object_name = "runs"
    paginate_by = 25

    def get_queryset(self):
        return (
            ProcessingRun.objects.filter(
                batch__status=UploadBatch.STATUS_PROCESSED,
            )
            .select_related("batch__distributor", "template_version__template")
            .order_by("-started_at")
        )


class ReviewBatchView(LoginRequiredMixin, StaffOrAdminMixin, View):
    """Row-level review for a ProcessingRun."""

    template_name = "review/review_batch.html"

    def get(self, request, pk):
        from django.core.paginator import Paginator
        from apps.field_templates.models import StandardMasterField

        run = get_object_or_404(
            ProcessingRun.objects.select_related(
                "batch__distributor", "template_version__template"
            ),
            pk=pk,
        )
        if request.GET.get("summary_only"):
            return render(request, "review/partials/_review_summary.html", {"run": run})

        all_rows = run.import_rows.order_by("row_number")

        # Counts for filter tabs
        counts = {
            "all":      all_rows.count(),
            "pending":  all_rows.filter(review_decision=ImportRow.DECISION_PENDING).count(),
            "approved": all_rows.filter(review_decision=ImportRow.DECISION_APPROVED).count(),
            "rejected": all_rows.filter(review_decision=ImportRow.DECISION_REJECTED).count(),
            "problem":  all_rows.filter(row_status__in=["invalid", "warning"]).count(),
        }

        # Apply filter
        filter_type = request.GET.get("filter", "all")
        if filter_type == "pending":
            rows_qs = all_rows.filter(review_decision=ImportRow.DECISION_PENDING)
        elif filter_type == "approved":
            rows_qs = all_rows.filter(review_decision=ImportRow.DECISION_APPROVED)
        elif filter_type == "rejected":
            rows_qs = all_rows.filter(review_decision=ImportRow.DECISION_REJECTED)
        elif filter_type == "problem":
            rows_qs = all_rows.filter(row_status__in=["invalid", "warning"])
        else:
            filter_type = "all"
            rows_qs = all_rows

        rows_qs = rows_qs.prefetch_related("validation_issues")

        # Derive column definitions from the first row's mapped_data
        sample = all_rows.first()
        columns = []
        if sample and sample.mapped_data:
            data_keys = list(sample.mapped_data.keys())
            field_display_map = {
                sf.name: sf.display_name
                for sf in StandardMasterField.objects.filter(name__in=data_keys)
            }
            columns = [
                (k, field_display_map.get(k, k.replace("_", " ").title()))
                for k in data_keys
            ]

        # Paginate
        paginator = Paginator(rows_qs, 100)
        rows = paginator.get_page(request.GET.get("page", 1))

        return render(request, self.template_name, {
            "run": run,
            "rows": rows,
            "columns": columns,
            "filter_type": filter_type,
            "counts": counts,
        })


class ApproveRowView(LoginRequiredMixin, HtmxMixin, View):
    """HTMX: approve a single import row, return updated row card partial."""

    def post(self, request, pk):
        row = get_object_or_404(ImportRow, pk=pk)
        note = request.POST.get("note", "")
        _apply_row_decision(row, "approved", note, request.user)
        return _row_response(request, row)


class RejectRowView(LoginRequiredMixin, HtmxMixin, View):
    """HTMX: reject a single import row, return updated row card partial."""

    def post(self, request, pk):
        row = get_object_or_404(ImportRow, pk=pk)
        note = request.POST.get("note", "")
        _apply_row_decision(row, "rejected", note, request.user)
        return _row_response(request, row)


class ApproveAllView(LoginRequiredMixin, StaffOrAdminMixin, View):
    """Approve all pending rows in a ProcessingRun."""

    def post(self, request, pk):
        run = get_object_or_404(ProcessingRun, pk=pk)
        rows = list(run.import_rows.filter(review_decision=ImportRow.DECISION_PENDING))
        count = len(rows)
        for row in rows:
            _apply_row_decision(row, "approved", "Bulk approved", request.user)
        messages.success(request, f"Approved {count} rows.")
        return redirect(reverse("review:review_batch", kwargs={"pk": pk}))


class RejectAllView(LoginRequiredMixin, StaffOrAdminMixin, View):
    """Reject all pending rows in a ProcessingRun."""

    def post(self, request, pk):
        run = get_object_or_404(ProcessingRun, pk=pk)
        rows = list(run.import_rows.filter(review_decision=ImportRow.DECISION_PENDING))
        count = len(rows)
        for row in rows:
            _apply_row_decision(row, "rejected", "Bulk rejected", request.user)
        messages.success(request, f"Rejected {count} rows.")
        return redirect(reverse("review:review_batch", kwargs={"pk": pk}))


class FinalizeView(LoginRequiredMixin, StaffOrAdminMixin, View):
    """Promote all approved rows to MasterData."""

    def post(self, request, pk):
        run = get_object_or_404(ProcessingRun, pk=pk)

        # Block if any rows are still pending review
        pending = run.import_rows.filter(review_decision=ImportRow.DECISION_PENDING).count()
        if pending > 0:
            messages.error(request, f"Cannot finalize: {pending} row(s) still pending review. Review all rows first.")
            return redirect(reverse("review:review_batch", kwargs={"pk": pk}))

        # Only promote approved rows — rejected are skipped
        approved_rows = run.import_rows.filter(review_decision=ImportRow.DECISION_APPROVED)
        from apps.master_data.models import MasterDataRecord
        from apps.field_templates.models import StandardMasterField

        standard_fields = list(StandardMasterField.objects.order_by("order", "name"))

        created_count = 0
        for row in approved_rows:
            normalized_data = _normalize_for_master(row.mapped_data, standard_fields)
            _, created = MasterDataRecord.objects.get_or_create(
                import_row=row,
                defaults={
                    "distributor": run.batch.distributor,
                    "area": run.batch.distributor.area.name,
                    "template_version": run.template_version,
                    "processing_run": run,
                    "data": normalized_data,
                    "business_key": row.business_key,
                },
            )
            if created:
                created_count += 1

        total_approved = approved_rows.count()
        skipped = total_approved - created_count  # already existed
        msg = f"Finalized: {created_count} record(s) added to Master Data."
        if skipped:
            msg += f" ({skipped} already existed and were skipped.)"
        messages.success(request, msg)
        return redirect(reverse("review:review_batch", kwargs={"pk": pk}))


def _row_response(request, row: ImportRow):
    """Return the table row partial for HTMX swap."""
    from apps.field_templates.models import StandardMasterField
    row.refresh_from_db()

    data_keys = list(row.mapped_data.keys())
    field_display_map = {
        sf.name: sf.display_name
        for sf in StandardMasterField.objects.filter(name__in=data_keys)
    }
    columns = [
        (k, field_display_map.get(k, k.replace("_", " ").title()))
        for k in data_keys
    ]

    response = render(
        request,
        "review/partials/_row_tr.html",
        {"row": row, "columns": columns},
    )
    response["HX-Trigger"] = "reviewSummaryChanged"
    return response

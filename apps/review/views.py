"""Review workflow views — file-level and row-level."""
from __future__ import annotations

from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.generic import ListView, View

from apps.core.mixins import HtmxMixin, StaffOrAdminMixin
from apps.distributors.models import get_user_distributors
from apps.field_templates.models import StandardMasterField
from apps.master_data.models import MasterDataImport, MasterDataRecord
from apps.uploads.models import ImportRow, ProcessingRun, UploadBatch, ValidationIssue
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
    if decision == ImportRow.DECISION_APPROVED:
        import_row.row_status = ImportRow.ROW_STATUS_APPROVED
    elif decision == ImportRow.DECISION_REJECTED:
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
    """File-level review queue with approval status filter."""
    model = ProcessingRun
    template_name = "review/review_queue.html"
    context_object_name = "runs"
    paginate_by = 25

    STATUS_FILTER_CHOICES = [
        ("", "All"),
        ("not_reviewed", "Not Reviewed"),
        ("approved_all", "Approved All"),
        ("partially_approved", "Partially Approved"),
        ("rejected_all", "Rejected All"),
    ]

    def get_queryset(self):
        qs = (
            ProcessingRun.objects.filter(
                batch__status=UploadBatch.STATUS_PROCESSED,
            )
            .select_related("batch__distributor", "template_version__template")
            .order_by("-started_at")
        )

        status_filter = self.request.GET.get("status", "").strip()
        if status_filter:
            # Filter in Python since approval_status is a property, not a DB field
            # Fetch all, then filter — acceptable for review queue size
            pks = [run.pk for run in qs if run.approval_status == status_filter]
            qs = qs.filter(pk__in=pks)

        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["status_filter_choices"] = self.STATUS_FILTER_CHOICES
        ctx["selected_status"] = self.request.GET.get("status", "")
        return ctx


class ReviewBatchView(LoginRequiredMixin, StaffOrAdminMixin, View):
    """Row-level review for a ProcessingRun."""

    template_name = "review/review_batch.html"

    def get(self, request, pk):
        from django.core.paginator import Paginator


        run = get_object_or_404(
            ProcessingRun.objects.select_related(
                "batch__distributor", "template_version__template"
            ),
            pk=pk,
        )
        if request.GET.get("summary_only"):
            return render(request, "review/partials/_review_summary.html", {"run": run})

        all_rows = run.import_rows.order_by("row_number")

        # Counts for filter tabs (single query with conditional aggregation)
        from django.db.models import Count, Q
        agg = all_rows.aggregate(
            total=Count("pk"),
            pending=Count("pk", filter=Q(review_decision=ImportRow.DECISION_PENDING)),
            approved=Count("pk", filter=Q(review_decision=ImportRow.DECISION_APPROVED)),
            rejected=Count("pk", filter=Q(review_decision=ImportRow.DECISION_REJECTED)),
            problem=Count("pk", filter=Q(row_status__in=["invalid", "warning"])),
        )
        counts = {
            "all": agg["total"],
            "pending": agg["pending"],
            "approved": agg["approved"],
            "rejected": agg["rejected"],
            "problem": agg["problem"],
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

        # Split fields into header (document-level) vs table (row-level)
        all_active_fields = StandardMasterField.objects.filter(is_active=True).order_by("order")
        displayed_fields = [sf for sf in all_active_fields if sf.is_displayed]

        # Determine which fields are "header" (from HeaderFieldMapping or batch_context)
        header_field_names = set()
        if run.template_version:
            header_field_names = set(
                hm.standard_field.name
                for hm in run.template_version.header_mappings.select_related("standard_field")
            )
        for sf in all_active_fields:
            if sf.batch_context_source:
                header_field_names.add(sf.name)

        # Table columns = only displayed fields that are NOT header
        table_columns = [(sf.name, sf.display_name) for sf in displayed_fields if sf.name not in header_field_names]

        # Header data = ALL active header fields (even if is_displayed=False)
        header_fields = [(sf.name, sf.display_name) for sf in all_active_fields if sf.name in header_field_names]

        # Get header values from first row
        first_row = all_rows.first()
        header_values = []
        if first_row and header_fields:
            for name, label in header_fields:
                val = first_row.mapped_data.get(name, "")
                if val:
                    header_values.append((label, val))

        # Paginate
        paginator = Paginator(rows_qs, 100)
        rows = paginator.get_page(request.GET.get("page", 1))

        return render(request, self.template_name, {
            "run": run,
            "rows": rows,
            "columns": table_columns,
            "header_values": header_values,
            "filter_type": filter_type,
            "counts": counts,
        })


class ApproveRowView(LoginRequiredMixin, HtmxMixin, View):
    """HTMX: approve a single import row. Check product exists in distributor warehouse."""

    def post(self, request, pk):
        row = get_object_or_404(ImportRow.objects.select_related("processing_run__batch__distributor"), pk=pk)
        note = request.POST.get("note", "")

        # Check product exists in distributor warehouse
        from apps.warehouse.services.stock import check_product_exists
        check = check_product_exists(row, row.processing_run.batch.distributor)
        if check and not check["found"]:
            # Product not found → mark as problem (invalid + warning)

            row.row_status = ImportRow.ROW_STATUS_INVALID
            row.review_decision = ImportRow.DECISION_PENDING
            row.save(update_fields=["row_status", "review_decision"])
            ValidationIssue.objects.create(
                import_row=row,
                category="business",
                severity="error",
                code="PRODUCT_NOT_IN_WAREHOUSE",
                message=f"Product '{check['value']}' not found in distributor warehouse.",
                field_name="item_name",
            )
            return _row_response(request, row)

        _apply_row_decision(row, ImportRow.DECISION_APPROVED, note, request.user)
        from apps.core.services import log_activity
        from apps.core.models import ActivityLog
        log_activity(
            user=request.user,
            action=ActivityLog.ACTION_APPROVE,
            description=f"Approved row {row.row_number} in batch '{row.processing_run.batch.original_filename}'",
            target=row,
            details={"batch_id": row.processing_run.batch_id, "row_number": row.row_number},
            request=request,
        )
        return _row_response(request, row)


class RejectRowView(LoginRequiredMixin, HtmxMixin, View):
    """HTMX: reject a single import row, return updated row card partial."""

    def post(self, request, pk):
        row = get_object_or_404(ImportRow.objects.select_related("processing_run__batch"), pk=pk)
        note = request.POST.get("note", "")
        _apply_row_decision(row, ImportRow.DECISION_REJECTED, note, request.user)
        from apps.core.services import log_activity
        from apps.core.models import ActivityLog
        log_activity(
            user=request.user,
            action=ActivityLog.ACTION_REJECT,
            description=f"Rejected row {row.row_number} in batch '{row.processing_run.batch.original_filename}'",
            target=row,
            details={"batch_id": row.processing_run.batch_id, "row_number": row.row_number, "note": note},
            request=request,
        )
        return _row_response(request, row)


class ApproveAllView(LoginRequiredMixin, StaffOrAdminMixin, View):
    """Approve all pending rows. Rows without matching product → problem."""

    def post(self, request, pk):
        run = get_object_or_404(ProcessingRun.objects.select_related("batch__distributor"), pk=pk)
        rows = list(run.import_rows.filter(review_decision=ImportRow.DECISION_PENDING))
        distributor = run.batch.distributor

        # Check products for all rows
        from apps.warehouse.services.stock import check_products_for_rows
        from apps.uploads.models import ValidationIssue
        checks = check_products_for_rows(rows, distributor)

        approved_count = 0
        problem_count = 0
        for row in rows:
            check = checks.get(row.pk)
            if check and not check["found"]:
                # Product not found → mark as problem
                row.row_status = ImportRow.ROW_STATUS_INVALID
                row.save(update_fields=["row_status"])
                ValidationIssue.objects.create(
                    import_row=row,
                    category="business",
                    severity="error",
                    code="PRODUCT_NOT_IN_WAREHOUSE",
                    message=f"Product '{check['value']}' not found in distributor warehouse.",
                    field_name="item_name",
                )
                problem_count += 1
            else:
                _apply_row_decision(row, ImportRow.DECISION_APPROVED, "Bulk approved", request.user)
                approved_count += 1

        msg = f"Approved {approved_count} rows."
        if problem_count:
            msg += f" {problem_count} row(s) marked as problem (product not in warehouse)."

        from apps.core.services import log_activity
        from apps.core.models import ActivityLog
        log_activity(
            user=request.user,
            action=ActivityLog.ACTION_APPROVE,
            description=f"Bulk approved {approved_count} rows in batch '{run.batch.original_filename}'",
            target=run.batch,
            details={"approved": approved_count, "problems": problem_count, "run_id": run.pk},
            request=request,
        )
        messages.success(request, msg)
        return redirect(reverse("review:review_batch", kwargs={"pk": pk}))


class RejectAllView(LoginRequiredMixin, StaffOrAdminMixin, View):
    """Reject all pending rows in a ProcessingRun."""

    def post(self, request, pk):
        run = get_object_or_404(ProcessingRun.objects.select_related("batch"), pk=pk)
        rows = list(run.import_rows.filter(review_decision=ImportRow.DECISION_PENDING))
        count = len(rows)
        for row in rows:
            _apply_row_decision(row, ImportRow.DECISION_REJECTED, "Bulk rejected", request.user)

        from apps.core.services import log_activity
        from apps.core.models import ActivityLog
        log_activity(
            user=request.user,
            action=ActivityLog.ACTION_REJECT,
            description=f"Bulk rejected {count} rows in batch '{run.batch.original_filename}'",
            target=run.batch,
            details={"rejected": count, "run_id": run.pk},
            request=request,
        )
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



        standard_fields = list(StandardMasterField.objects.order_by("order", "name"))

        # Create import group
        master_import = MasterDataImport.objects.create(
            code=MasterDataImport.generate_code(),
            distributor=run.batch.distributor,
            processing_run=run,
            imported_by=request.user,
        )

        # ── Optimized: bulk_create instead of per-row get_or_create ──────
        approved_rows_list = list(approved_rows)

        # 1. Find already-finalized rows (skip duplicates)
        existing_row_ids = set(
            MasterDataRecord.objects.filter(
                import_row__in=approved_rows_list
            ).values_list("import_row_id", flat=True)
        )
        new_rows = [r for r in approved_rows_list if r.pk not in existing_row_ids]

        # 2. Enrich with master product name if warehouse is configured
        from apps.warehouse.services.stock import match_distributor_product
        from apps.warehouse.models import WarehouseFieldConfig
        wh_config = WarehouseFieldConfig.load()
        product_field = wh_config.product_identifier_field if wh_config else None

        # 3. Build records + bulk_create
        records_to_create = []
        for row in new_rows:
            normalized_data = _normalize_for_master(row.mapped_data, standard_fields)

            # Enrich: add master product name from warehouse
            if product_field:
                product_value = str(row.mapped_data.get(product_field, "")).strip()
                if product_value:
                    dp = match_distributor_product(run.batch.distributor, product_value)
                    if dp:
                        normalized_data["_product_master_name"] = dp.product.name
                        normalized_data["_product_master_sku"] = dp.product.sku

            records_to_create.append(MasterDataRecord(
                import_row=row,
                master_import=master_import,
                distributor=run.batch.distributor,
                area=run.batch.distributor.area.name,
                template_version=run.template_version,
                processing_run=run,
                data=normalized_data,
                business_key=row.business_key,
            ))

        if records_to_create:
            MasterDataRecord.objects.bulk_create(records_to_create)

        created_count = len(records_to_create)
        skipped_count = len(existing_row_ids)

        # Update record count
        master_import.record_count = created_count
        master_import.save(update_fields=["record_count"])

        if created_count == 0:
            master_import.delete()

        msg = f"Finalized: {created_count} record(s) added to Master Data."
        if created_count > 0:
            msg += f" (Import ID: {master_import.code})"
        if skipped_count:
            msg += f" ({skipped_count} already existed and were skipped.)"

        # Deduct stock on finalize
        if created_count > 0:
            from apps.warehouse.services.stock import reduce_stock_for_rows
            stock_result = reduce_stock_for_rows(
                distributor=run.batch.distributor,
                rows=new_rows,
                user=request.user,
                reference=f"Finalize (Import {master_import.code})",
            )
            if not stock_result.get("skipped"):
                msg += f" Stock deducted for {stock_result['matched']} product(s)."

        # Activity log
        if created_count > 0:
            from apps.core.services import log_activity
            from apps.core.models import ActivityLog
            log_activity(
                user=request.user,
                action=ActivityLog.ACTION_FINALIZE,
                description=f"Finalized {created_count} record(s) to Master Data from '{run.batch.original_filename}'",
                target=master_import,
                details={
                    "import_code": master_import.code,
                    "records": created_count,
                    "skipped": skipped_count,
                    "batch_id": run.batch_id,
                },
                request=request,
            )

        messages.success(request, msg)
        return redirect(reverse("review:review_batch", kwargs={"pk": pk}))


def _row_response(request, row: ImportRow):
    """Return the table row partial for HTMX swap."""

    row.refresh_from_db()

    displayed_fields = StandardMasterField.objects.filter(
        is_active=True, is_displayed=True
    ).order_by("order")

    # Exclude header fields (same logic as ReviewBatchView)
    header_field_names = set()
    if row.processing_run.template_version:
        header_field_names = set(
            hm.standard_field.name
            for hm in row.processing_run.template_version.header_mappings.select_related("standard_field")
        )
    for sf in displayed_fields:
        if sf.batch_context_source:
            header_field_names.add(sf.name)

    columns = [(sf.name, sf.display_name) for sf in displayed_fields if sf.name not in header_field_names]

    response = render(
        request,
        "review/partials/_row_tr.html",
        {"row": row, "columns": columns},
    )
    response["HX-Trigger"] = "reviewSummaryChanged"
    return response

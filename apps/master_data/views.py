"""Master Data views — browse, filter, and export approved records."""
from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import get_object_or_404, redirect, render
from django.views.generic import DetailView, ListView, View

from apps.core.mixins import HtmxMixin
from apps.field_templates.models import StandardMasterField
from .forms import ExportForm
from .models import MasterDataImport, MasterDataRecord
from .services.export import export_master_data


# ── Import List (grouped view) ─────────────────────────────────────────────


class ImportListView(LoginRequiredMixin, HtmxMixin, ListView):
    """Top-level list: shows MasterDataImport groups."""
    model = MasterDataImport
    template_name = "master_data/import_list.html"
    context_object_name = "imports"
    paginate_by = 50

    def get_queryset(self):
        from apps.distributors.models import get_user_distributors
        user = self.request.user
        qs = MasterDataImport.objects.select_related("distributor", "imported_by")

        if not (user.is_admin or user.is_superuser):
            qs = qs.filter(distributor__in=get_user_distributors(user))

        distributor_id = self.request.GET.get("distributor", "").strip()
        if distributor_id:
            qs = qs.filter(distributor_id=distributor_id)
        q = self.request.GET.get("q", "").strip()
        if q:
            qs = qs.filter(code__icontains=q)

        return qs.order_by("-imported_at")

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        from apps.distributors.models import Distributor, get_user_distributors
        user = self.request.user
        if user.is_admin or user.is_superuser:
            ctx["distributors"] = Distributor.objects.filter(is_active=True).order_by("name")
        else:
            ctx["distributors"] = get_user_distributors(user).order_by("name")
        ctx["filter_distributor"] = self.request.GET.get("distributor", "")
        ctx["filter_q"] = self.request.GET.get("q", "")
        return ctx


# ── Import Detail (records in a group) ──────────────────────────────────────


class ImportDetailView(LoginRequiredMixin, ListView):
    """Shows all records in one MasterDataImport."""
    model = MasterDataRecord
    template_name = "master_data/import_detail.html"
    context_object_name = "records"
    paginate_by = 100

    def get_queryset(self):
        self.master_import = get_object_or_404(
            MasterDataImport.objects.select_related("distributor"),
            pk=self.kwargs["pk"],
        )
        return MasterDataRecord.objects.filter(
            master_import=self.master_import
        ).order_by("pk")

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["master_import"] = self.master_import
        ctx["standard_fields"] = StandardMasterField.objects.filter(
            is_active=True, is_displayed=True
        ).order_by("order")
        return ctx


# ── Record Detail (single record) ──────────────────────────────────────────


class RecordDetailView(LoginRequiredMixin, DetailView):
    model = MasterDataRecord
    template_name = "master_data/record_detail.html"
    context_object_name = "record"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        displayed_fields = StandardMasterField.objects.filter(
            is_active=True, is_displayed=True
        ).order_by("order")
        record = self.object
        ctx["data_columns"] = [
            (sf.name, sf.display_name, record.data.get(sf.name, ""))
            for sf in displayed_fields
            if sf.name in record.data
        ]
        # Master product info (enriched during finalize)
        ctx["product_master_name"] = record.data.get("_product_master_name", "")
        ctx["product_master_sku"] = record.data.get("_product_master_sku", "")
        return ctx


# ── Import Delete ───────────────────────────────────────────────────────────


class ImportDeleteView(LoginRequiredMixin, View):
    def post(self, request, pk):
        mi = get_object_or_404(MasterDataImport, pk=pk)
        if not (request.user.is_admin or request.user.is_superuser):
            messages.error(request, "Only admins can delete imports.")
            return redirect("master_data:record_list")
        code = mi.code
        count = mi.records.count()
        mi.delete()  # cascades to records
        messages.success(request, f"Deleted import {code} ({count} records).")
        return redirect("master_data:record_list")


# ── Bulk Delete (legacy, kept for compatibility) ────────────────────────────


class BulkDeleteView(LoginRequiredMixin, View):
    def post(self, request):
        from apps.distributors.models import get_user_distributors

        ids = request.POST.getlist("selected_ids")
        if not ids:
            messages.warning(request, "No imports selected.")
            return redirect("master_data:record_list")

        qs = MasterDataImport.objects.filter(pk__in=ids)
        if not (request.user.is_admin or request.user.is_superuser):
            qs = qs.filter(distributor__in=get_user_distributors(request.user))

        count = qs.count()
        qs.delete()
        messages.success(request, f"Deleted {count} import(s).")
        return redirect("master_data:record_list")


# ── Export ──────────────────────────────────────────────────────────────────


class ExportView(LoginRequiredMixin, View):
    template_name = "master_data/export_form.html"

    def get(self, request):
        form = ExportForm(request.GET or None)
        return render(request, self.template_name, {"form": form})

    def post(self, request):
        form = ExportForm(request.POST)
        if not form.is_valid():
            return render(request, self.template_name, {"form": form})

        from apps.distributors.models import get_user_distributors
        qs = MasterDataRecord.objects.select_related("distributor")

        if not (request.user.is_admin or request.user.is_superuser):
            qs = qs.filter(distributor__in=get_user_distributors(request.user))

        if form.cleaned_data.get("area"):
            qs = qs.filter(area=form.cleaned_data["area"])
        if form.cleaned_data.get("distributor"):
            qs = qs.filter(distributor=form.cleaned_data["distributor"])
        if form.cleaned_data.get("date_from"):
            qs = qs.filter(imported_at__date__gte=form.cleaned_data["date_from"])
        if form.cleaned_data.get("date_to"):
            qs = qs.filter(imported_at__date__lte=form.cleaned_data["date_to"])

        standard_fields = list(StandardMasterField.objects.filter(
            is_active=True, is_displayed=True
        ).order_by("order"))
        fmt = form.cleaned_data["format"]
        return export_master_data(qs, fmt, standard_fields)

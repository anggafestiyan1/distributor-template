"""Master Data views — browse, filter, and export approved records."""
from __future__ import annotations

from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import redirect, render
from django.views.generic import DetailView, ListView, View

from apps.core.mixins import HtmxMixin
from apps.field_templates.models import StandardMasterField
from .forms import ExportForm
from .models import MasterDataRecord
from .services.export import export_master_data


class RecordListView(LoginRequiredMixin, HtmxMixin, ListView):
    model = MasterDataRecord
    template_name = "master_data/record_list.html"
    context_object_name = "records"
    paginate_by = 50

    def get_queryset(self):
        from apps.distributors.models import get_user_distributors
        user = self.request.user
        qs = MasterDataRecord.objects.select_related("distributor", "template_version")

        if not (user.is_admin or user.is_superuser):
            qs = qs.filter(distributor__in=get_user_distributors(user))

        area = self.request.GET.get("area", "").strip()
        distributor_id = self.request.GET.get("distributor", "").strip()
        date_from = self.request.GET.get("date_from", "").strip()
        date_to = self.request.GET.get("date_to", "").strip()
        q = self.request.GET.get("q", "").strip()

        if area:
            qs = qs.filter(area=area)   # exact — area is selected from dropdown
        if distributor_id:
            qs = qs.filter(distributor_id=distributor_id)
        try:
            if date_from:
                qs = qs.filter(imported_at__date__gte=date_from)
            if date_to:
                qs = qs.filter(imported_at__date__lte=date_to)
        except Exception:
            pass
        if q:
            qs = qs.filter(business_key__icontains=q)

        return qs.order_by("-imported_at")

    def get_template_names(self):
        if self.is_htmx:
            return ["master_data/partials/_record_table.html"]
        return [self.template_name]

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        from apps.distributors.models import Area, Distributor, get_user_distributors
        user = self.request.user

        # Scope areas and distributors to what the user can see
        if user.is_admin or user.is_superuser:
            accessible_distributors = Distributor.objects.filter(is_active=True)
            ctx["areas"] = Area.objects.filter(is_active=True).order_by("name")
        else:
            accessible_distributors = get_user_distributors(user)
            area_ids = accessible_distributors.values_list("area_id", flat=True)
            ctx["areas"] = Area.objects.filter(pk__in=area_ids, is_active=True).order_by("name")

        ctx["distributors"] = accessible_distributors.order_by("name")
        ctx["standard_fields"] = StandardMasterField.objects.filter(is_active=True).order_by("order")
        ctx["filter_area"] = self.request.GET.get("area", "")
        ctx["filter_distributor"] = self.request.GET.get("distributor", "")
        ctx["filter_date_from"] = self.request.GET.get("date_from", "")
        ctx["filter_date_to"] = self.request.GET.get("date_to", "")
        ctx["filter_q"] = self.request.GET.get("q", "")
        return ctx


class RecordDetailView(LoginRequiredMixin, DetailView):
    model = MasterDataRecord
    template_name = "master_data/record_detail.html"
    context_object_name = "record"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        record = self.object
        # Build display map from current standard fields (may be incomplete if fields deleted)
        field_display_map = {
            sf.name: sf.display_name
            for sf in StandardMasterField.objects.all()
        }
        # Derive columns from actual stored data keys — preserves data even if field deleted
        ctx["data_columns"] = [
            (key, field_display_map.get(key, key.replace("_", " ").title()), value)
            for key, value in record.data.items()
        ]
        return ctx


class BulkDeleteView(LoginRequiredMixin, View):
    def _base_qs(self, request):
        """Return queryset scoped to the current user."""
        from apps.distributors.models import get_user_distributors
        qs = MasterDataRecord.objects.all()
        if not (request.user.is_admin or request.user.is_superuser):
            qs = qs.filter(distributor__in=get_user_distributors(request.user))
        return qs

    def _apply_filters(self, qs, post):
        """Apply the same filters passed from the list page."""
        area = post.get("area", "").strip()
        distributor_id = post.get("distributor", "").strip()
        date_from = post.get("date_from", "").strip()
        date_to = post.get("date_to", "").strip()
        q = post.get("q", "").strip()
        if area:
            qs = qs.filter(area=area)
        if distributor_id:
            qs = qs.filter(distributor_id=distributor_id)
        try:
            if date_from:
                qs = qs.filter(imported_at__date__gte=date_from)
            if date_to:
                qs = qs.filter(imported_at__date__lte=date_to)
        except Exception:
            pass
        if q:
            qs = qs.filter(business_key__icontains=q)
        return qs

    def post(self, request):
        from django.contrib import messages

        delete_all = request.POST.get("delete_all") == "1"

        if delete_all:
            qs = self._apply_filters(self._base_qs(request), request.POST)
        else:
            ids = request.POST.getlist("selected_ids")
            if not ids:
                messages.warning(request, "No records selected.")
                return redirect("master_data:record_list")
            qs = self._base_qs(request).filter(pk__in=ids)

        count = qs.count()
        qs.delete()
        messages.success(request, f"Deleted {count} record(s).")
        return redirect("master_data:record_list")


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
            qs = qs.filter(area__icontains=form.cleaned_data["area"])
        if form.cleaned_data.get("distributor"):
            qs = qs.filter(distributor=form.cleaned_data["distributor"])
        if form.cleaned_data.get("date_from"):
            qs = qs.filter(imported_at__date__gte=form.cleaned_data["date_from"])
        if form.cleaned_data.get("date_to"):
            qs = qs.filter(imported_at__date__lte=form.cleaned_data["date_to"])

        standard_fields = list(StandardMasterField.objects.order_by("order"))
        fmt = form.cleaned_data["format"]
        return export_master_data(qs, fmt, standard_fields)

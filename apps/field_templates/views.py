"""Field templates management views."""
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db import IntegrityError
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse, reverse_lazy
from django.views.generic import CreateView, DetailView, ListView, UpdateView, View

from apps.core.mixins import StaffOrAdminMixin
from .forms import (
    FieldAliasFormSet,
    StandardMasterFieldForm,
    TemplateFieldMappingFormSet,
    TemplateForm,
    TemplateVersionForm,
)
from .models import StandardMasterField, Template, TemplateVersion


# ── Standard Master Fields ────────────────────────────────────────────────────

class FieldListView(LoginRequiredMixin, StaffOrAdminMixin, ListView):
    model = StandardMasterField
    template_name = "field_templates/field_list.html"
    context_object_name = "fields"
    ordering = ["order", "name"]


class FieldCreateView(LoginRequiredMixin, StaffOrAdminMixin, CreateView):
    model = StandardMasterField
    form_class = StandardMasterFieldForm
    template_name = "field_templates/field_form.html"

    def get_success_url(self):
        return reverse("field_templates:field_aliases", kwargs={"pk": self.object.pk})

    def form_valid(self, form):
        messages.success(self.request, "Field created.")
        return super().form_valid(form)


class FieldEditView(LoginRequiredMixin, StaffOrAdminMixin, UpdateView):
    model = StandardMasterField
    form_class = StandardMasterFieldForm
    template_name = "field_templates/field_form.html"
    success_url = reverse_lazy("field_templates:field_list")

    def form_valid(self, form):
        messages.success(self.request, "Field updated.")
        return super().form_valid(form)


class FieldDeleteView(LoginRequiredMixin, StaffOrAdminMixin, View):
    def post(self, request, pk):
        from django.db.models import ProtectedError
        field = get_object_or_404(StandardMasterField, pk=pk)
        name = field.display_name
        try:
            field.delete()
            messages.success(request, f"Field '{name}' deleted.")
        except ProtectedError as e:
            messages.error(request, str(e).split("set()")[0].strip().rstrip(","))
        except IntegrityError:
            messages.error(request, f"Cannot delete '{name}': it is used in one or more template mappings.")
        return redirect(reverse_lazy("field_templates:field_list"))


class FieldToggleActiveView(LoginRequiredMixin, StaffOrAdminMixin, View):
    def post(self, request, pk):
        field = get_object_or_404(StandardMasterField, pk=pk)
        field.is_active = not field.is_active
        field.save(update_fields=["is_active"])
        return redirect(reverse("field_templates:field_list"))


class FieldToggleDisplayedView(LoginRequiredMixin, StaffOrAdminMixin, View):
    def post(self, request, pk):
        field = get_object_or_404(StandardMasterField, pk=pk)
        field.is_displayed = not field.is_displayed
        field.save(update_fields=["is_displayed"])
        return redirect(reverse("field_templates:field_list"))


class FieldAliasView(LoginRequiredMixin, StaffOrAdminMixin, View):
    """Manage aliases for a StandardMasterField using an inline formset."""

    template_name = "field_templates/field_aliases.html"

    def get(self, request, pk):
        from django.shortcuts import render
        field = get_object_or_404(StandardMasterField, pk=pk)
        formset = FieldAliasFormSet(instance=field)
        return render(request, self.template_name, {"field": field, "formset": formset})

    def post(self, request, pk):
        from django.db import IntegrityError
        from django.shortcuts import render
        field = get_object_or_404(StandardMasterField, pk=pk)
        formset = FieldAliasFormSet(request.POST, instance=field)
        if formset.is_valid():
            try:
                formset.save()
                messages.success(request, "Aliases saved.")
                return redirect(reverse("field_templates:field_aliases", kwargs={"pk": pk}))
            except IntegrityError:
                messages.error(
                    request,
                    "One or more aliases duplicate an existing alias after normalization. "
                    "Please check for similar entries and try again.",
                )
        return render(request, self.template_name, {"field": field, "formset": formset})


# ── Templates ─────────────────────────────────────────────────────────────────

class TemplateListView(LoginRequiredMixin, StaffOrAdminMixin, ListView):
    model = Template
    template_name = "field_templates/template_list.html"
    context_object_name = "templates"

    def get_queryset(self):
        return Template.objects.select_related("distributor").order_by("name")

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        qs = self.get_queryset()
        ctx["global_templates"] = qs.filter(scope="global")
        ctx["assigned_templates"] = qs.filter(scope="assigned")
        return ctx


class TemplateCreateView(LoginRequiredMixin, StaffOrAdminMixin, CreateView):
    model = Template
    form_class = TemplateForm
    template_name = "field_templates/template_form.html"

    def get_initial(self):
        initial = super().get_initial()
        distributor_pk = self.request.GET.get("distributor")
        if distributor_pk:
            initial["scope"] = "assigned"
            initial["distributor"] = distributor_pk
        return initial

    def form_valid(self, form):
        form.instance.created_by = self.request.user
        self.object = form.save()
        # Auto-create first version
        version = TemplateVersion.objects.create(
            template=self.object,
            version_number=1,
            is_active=True,
            created_by=self.request.user,
        )
        messages.success(self.request, "Template created. Now add field mappings.")
        return redirect(reverse("field_templates:version_mappings", kwargs={"pk": version.pk}))


class TemplateDetailView(LoginRequiredMixin, StaffOrAdminMixin, DetailView):
    model = Template
    template_name = "field_templates/template_detail.html"
    context_object_name = "template"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["versions"] = self.object.versions.order_by("-version_number")
        return ctx


class TemplateEditView(LoginRequiredMixin, StaffOrAdminMixin, UpdateView):
    model = Template
    form_class = TemplateForm
    template_name = "field_templates/template_form.html"

    def get_success_url(self):
        return reverse("field_templates:template_detail", kwargs={"pk": self.object.pk})

    def form_valid(self, form):
        messages.success(self.request, "Template updated.")
        return super().form_valid(form)


class TemplateDeleteView(LoginRequiredMixin, StaffOrAdminMixin, View):
    def post(self, request, pk):
        template = get_object_or_404(Template, pk=pk)
        name = template.name
        # Check if any version is in use
        if template.versions.filter(processing_runs__isnull=False).exists():
            messages.error(request, f"Cannot delete '{name}': one or more versions are used in processing runs.")
            return redirect(reverse("field_templates:template_detail", kwargs={"pk": pk}))
        template.delete()
        messages.success(request, f"Template '{name}' deleted.")
        return redirect(reverse_lazy("field_templates:template_list"))


class VersionDeleteView(LoginRequiredMixin, StaffOrAdminMixin, View):
    def post(self, request, pk):
        version = get_object_or_404(TemplateVersion, pk=pk)
        template_pk = version.template_id
        if version.is_in_use:
            messages.error(request, f"Cannot delete v{version.version_number}: it is used in processing runs.")
            return redirect(reverse("field_templates:version_detail", kwargs={"pk": pk}))
        version.delete()
        messages.success(request, f"Version {version.version_number} deleted.")
        return redirect(reverse("field_templates:template_detail", kwargs={"pk": template_pk}))


class TemplateNewVersionView(LoginRequiredMixin, StaffOrAdminMixin, View):
    """Create a new TemplateVersion (cloning mappings from the latest)."""

    def post(self, request, pk):
        template = get_object_or_404(Template, pk=pk)
        latest = template.versions.order_by("-version_number").first()
        new_number = (latest.version_number + 1) if latest else 1
        new_version = TemplateVersion.objects.create(
            template=template,
            version_number=new_number,
            is_active=True,
            created_by=request.user,
            notes=request.POST.get("notes", ""),
        )
        # Clone mappings from latest version
        if latest:
            from .models import TemplateFieldMapping
            for mapping in latest.field_mappings.all():
                TemplateFieldMapping.objects.create(
                    template_version=new_version,
                    standard_field=mapping.standard_field,
                    source_column=mapping.source_column,
                )
        messages.success(request, f"Version {new_number} created.")
        return redirect(reverse("field_templates:version_mappings", kwargs={"pk": new_version.pk}))


class VersionDetailView(LoginRequiredMixin, StaffOrAdminMixin, DetailView):
    model = TemplateVersion
    template_name = "field_templates/template_version_detail.html"
    context_object_name = "version"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["mappings"] = self.object.field_mappings.select_related("standard_field")
        return ctx


class VersionMappingsView(LoginRequiredMixin, StaffOrAdminMixin, View):
    """Manage TemplateFieldMappings for a version using an inline formset."""

    template_name = "field_templates/version_mappings.html"

    def _get_version(self, pk):
        return get_object_or_404(TemplateVersion, pk=pk)

    def _ctx(self, version, formset):
        from django.shortcuts import render
        return {
            "version": version,
            "formset": formset,
            "standard_fields": StandardMasterField.objects.order_by("order", "name"),
        }

    def get(self, request, pk):
        from django.shortcuts import render
        version = self._get_version(pk)
        if version.is_in_use:
            messages.warning(
                request,
                "This version is in use and cannot be edited. Create a new version instead.",
            )
            return redirect(reverse("field_templates:version_detail", kwargs={"pk": pk}))
        formset = TemplateFieldMappingFormSet(instance=version)
        return render(request, self.template_name, self._ctx(version, formset))

    def post(self, request, pk):
        from django.shortcuts import render
        version = self._get_version(pk)
        if version.is_in_use:
            messages.error(request, "Cannot edit a version that is in use.")
            return redirect(reverse("field_templates:version_detail", kwargs={"pk": pk}))
        formset = TemplateFieldMappingFormSet(request.POST, instance=version)
        if formset.is_valid():
            formset.save()
            messages.success(request, "Mappings saved.")
            return redirect(
                reverse("field_templates:template_detail", kwargs={"pk": version.template_id})
            )
        return render(request, self.template_name, self._ctx(version, formset))


class FieldTemplateDownloadView(LoginRequiredMixin, StaffOrAdminMixin, View):
    """Download a sample .xlsx file with standard master field headers."""

    def get(self, request):
        import io
        from openpyxl import Workbook
        from openpyxl.styles import Font, PatternFill, Alignment
        from django.http import HttpResponse

        fields = list(StandardMasterField.objects.order_by("order", "name"))
        wb = Workbook()
        ws = wb.active
        ws.title = "Master Data Template"

        header_font = Font(bold=True, color="1B5E20")
        header_fill = PatternFill("solid", fgColor="E8F5E9")

        type_map = {
            "string": "text", "integer": "number", "decimal": "0.00",
            "date": "YYYY-MM-DD", "boolean": "true/false",
        }
        for col_idx, field in enumerate(fields, start=1):
            cell = ws.cell(row=1, column=col_idx, value=field.display_name)
            cell.font = header_font
            cell.fill = header_fill
            cell.alignment = Alignment(horizontal="left")
            ws.column_dimensions[cell.column_letter].width = max(len(field.display_name) + 4, 14)
            ws.cell(row=2, column=col_idx, value=type_map.get(field.data_type, field.data_type))

        buf = io.BytesIO()
        wb.save(buf)
        buf.seek(0)
        response = HttpResponse(
            buf.read(),
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        response["Content-Disposition"] = 'attachment; filename="master_data_template.xlsx"'
        return response

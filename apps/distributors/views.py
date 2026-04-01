"""Distributor and Area management views."""
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db import IntegrityError
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse_lazy
from django.views.generic import CreateView, DetailView, ListView, UpdateView, View

from apps.core.mixins import AdminRequiredMixin, StaffOrAdminMixin
from .forms import AreaForm, AssignmentForm, DistributorForm
from .models import Area, Distributor, UserDistributorAssignment


# ── Area ─────────────────────────────────────────────────────────────────────

class AreaListView(LoginRequiredMixin, StaffOrAdminMixin, ListView):
    model = Area
    template_name = "distributors/area_list.html"
    context_object_name = "areas"
    paginate_by = 25

    def get_queryset(self):
        qs = Area.objects.all()
        q = self.request.GET.get("q", "").strip()
        if q:
            qs = qs.filter(name__icontains=q) | qs.filter(code__icontains=q)
        return qs.order_by("name")


class AreaCreateView(LoginRequiredMixin, AdminRequiredMixin, CreateView):
    model = Area
    form_class = AreaForm
    template_name = "distributors/area_form.html"
    success_url = reverse_lazy("distributors:area_list")

    def form_valid(self, form):
        messages.success(self.request, "Area created.")
        return super().form_valid(form)


class AreaEditView(LoginRequiredMixin, AdminRequiredMixin, UpdateView):
    model = Area
    form_class = AreaForm
    template_name = "distributors/area_form.html"
    success_url = reverse_lazy("distributors:area_list")

    def form_valid(self, form):
        messages.success(self.request, "Area updated.")
        return super().form_valid(form)


class AreaDeleteView(LoginRequiredMixin, AdminRequiredMixin, View):
    def post(self, request, pk):
        area = get_object_or_404(Area, pk=pk)
        try:
            area.delete()
            messages.success(request, f"Area '{area.name}' deleted.")
        except IntegrityError:
            messages.error(request, f"Cannot delete '{area.name}': it is assigned to one or more distributors.")
        return redirect(reverse_lazy("distributors:area_list"))


# ── Distributor ───────────────────────────────────────────────────────────────

class DistributorListView(LoginRequiredMixin, StaffOrAdminMixin, ListView):
    model = Distributor
    template_name = "distributors/distributor_list.html"
    context_object_name = "distributors"
    paginate_by = 25

    def get_queryset(self):
        qs = Distributor.objects.select_related("area")
        q = self.request.GET.get("q", "").strip()
        if q:
            qs = qs.filter(name__icontains=q) | qs.filter(code__icontains=q)
        return qs.order_by("name")


class DistributorCreateView(LoginRequiredMixin, AdminRequiredMixin, CreateView):
    model = Distributor
    form_class = DistributorForm
    template_name = "distributors/distributor_form.html"
    success_url = reverse_lazy("distributors:list")

    def form_valid(self, form):
        messages.success(self.request, "Distributor created.")
        return super().form_valid(form)


class DistributorEditView(LoginRequiredMixin, AdminRequiredMixin, UpdateView):
    model = Distributor
    form_class = DistributorForm
    template_name = "distributors/distributor_form.html"
    success_url = reverse_lazy("distributors:list")

    def form_valid(self, form):
        messages.success(self.request, "Distributor updated.")
        return super().form_valid(form)


class DistributorDeleteView(LoginRequiredMixin, AdminRequiredMixin, View):
    def post(self, request, pk):
        dist = get_object_or_404(Distributor, pk=pk)
        name = dist.name
        try:
            dist.delete()
            messages.success(request, f"Distributor '{name}' deleted.")
        except IntegrityError:
            messages.error(request, f"Cannot delete '{name}': it has associated uploads or data.")
        return redirect(reverse_lazy("distributors:list"))


class DistributorDetailView(LoginRequiredMixin, StaffOrAdminMixin, DetailView):
    model = Distributor
    template_name = "distributors/distributor_detail.html"
    context_object_name = "distributor"

    def get_queryset(self):
        return Distributor.objects.select_related("area")

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        from apps.field_templates.models import Template
        ctx["distributor_templates"] = (
            Template.objects
            .filter(distributor=self.object)
            .prefetch_related("versions")
            .order_by("name")
        )
        return ctx


# ── Assignments ───────────────────────────────────────────────────────────────

class AssignmentCreateView(LoginRequiredMixin, AdminRequiredMixin, CreateView):
    model = UserDistributorAssignment
    form_class = AssignmentForm
    template_name = "distributors/assignment_form.html"
    success_url = reverse_lazy("distributors:list")

    def form_valid(self, form):
        form.instance.assigned_by = self.request.user
        messages.success(self.request, "Assignment created.")
        return super().form_valid(form)


class AssignmentDeleteView(LoginRequiredMixin, AdminRequiredMixin, View):
    def post(self, request, *args, **kwargs):
        obj = get_object_or_404(UserDistributorAssignment, pk=kwargs["pk"])
        obj.delete()
        messages.success(request, "Assignment removed.")
        return redirect(reverse_lazy("distributors:list"))

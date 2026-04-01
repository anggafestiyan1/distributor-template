"""Account management views."""
from django.contrib import messages
from django.contrib.auth import views as auth_views
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse_lazy
from django.views.generic import CreateView, ListView, UpdateView, View

from apps.accounts.models import CustomUser
from apps.accounts.forms import CustomUserCreationForm, CustomUserChangeForm
from apps.core.mixins import AdminRequiredMixin


class LoginView(auth_views.LoginView):
    template_name = "accounts/login.html"


class LogoutView(auth_views.LogoutView):
    pass


class UserListView(LoginRequiredMixin, AdminRequiredMixin, ListView):
    model = CustomUser
    template_name = "accounts/user_list.html"
    context_object_name = "users"
    paginate_by = 25

    def get_queryset(self):
        qs = super().get_queryset()
        q = self.request.GET.get("q", "").strip()
        if q:
            qs = qs.filter(username__icontains=q) | qs.filter(email__icontains=q)
        return qs.order_by("username")


class UserCreateView(LoginRequiredMixin, AdminRequiredMixin, CreateView):
    model = CustomUser
    form_class = CustomUserCreationForm
    template_name = "accounts/user_form.html"
    success_url = reverse_lazy("accounts:user_list")

    def form_valid(self, form):
        messages.success(self.request, "User created successfully.")
        return super().form_valid(form)


class UserEditView(LoginRequiredMixin, AdminRequiredMixin, UpdateView):
    model = CustomUser
    form_class = CustomUserChangeForm
    template_name = "accounts/user_form.html"
    success_url = reverse_lazy("accounts:user_list")

    def form_valid(self, form):
        messages.success(self.request, "User updated successfully.")
        return super().form_valid(form)


class UserToggleActiveView(LoginRequiredMixin, AdminRequiredMixin, View):
    """Deactivate or reactivate a user account (does not delete data)."""

    def post(self, request, pk):
        user = get_object_or_404(CustomUser, pk=pk)
        if user == request.user:
            messages.error(request, "You cannot deactivate your own account.")
            return redirect(reverse_lazy("accounts:user_list"))
        user.is_active = not user.is_active
        user.save(update_fields=["is_active"])
        action = "activated" if user.is_active else "deactivated"
        messages.success(request, f"User '{user.username}' {action}.")
        return redirect(reverse_lazy("accounts:user_list"))


class UserDeleteView(LoginRequiredMixin, AdminRequiredMixin, View):
    """Hard-delete a user. Blocked if the user is the only superuser."""

    def post(self, request, pk):
        user = get_object_or_404(CustomUser, pk=pk)
        if user == request.user:
            messages.error(request, "You cannot delete your own account.")
            return redirect(reverse_lazy("accounts:user_list"))
        username = user.username
        user.delete()
        messages.success(request, f"User '{username}' deleted.")
        return redirect(reverse_lazy("accounts:user_list"))

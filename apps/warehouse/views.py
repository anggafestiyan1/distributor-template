"""Warehouse views — products, stock management, movements, and configuration."""
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db import IntegrityError
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse, reverse_lazy
from django.views.generic import CreateView, ListView, UpdateView, View

from apps.core.mixins import AdminRequiredMixin
from apps.distributors.models import get_user_distributors
from .forms import (
    DistributorProductForm,
    ProductForm,
    StockAdjustForm,
    WarehouseConfigForm,
)
from apps.distributors.models import Distributor
from .models import (
    DistributorProduct,
    DistributorStock,
    MovementBatch,
    Product,
    StockMovement,
    WarehouseFieldConfig,
)


# ── Product CRUD ────────────────────────────────────────────────────────────


class ProductListView(LoginRequiredMixin, AdminRequiredMixin, ListView):
    model = Product
    template_name = "warehouse/product_list.html"
    context_object_name = "products"
    paginate_by = 50

    def get_queryset(self):
        qs = Product.objects.all()
        q = self.request.GET.get("q", "").strip()
        if q:
            qs = qs.filter(sku__icontains=q) | qs.filter(name__icontains=q)
        return qs.order_by("name")


class ProductCreateView(LoginRequiredMixin, AdminRequiredMixin, CreateView):
    model = Product
    form_class = ProductForm
    template_name = "warehouse/product_form.html"
    success_url = reverse_lazy("warehouse:product_list")

    def form_valid(self, form):
        messages.success(self.request, "Product created.")
        return super().form_valid(form)


class ProductEditView(LoginRequiredMixin, AdminRequiredMixin, UpdateView):
    model = Product
    form_class = ProductForm
    template_name = "warehouse/product_form.html"
    success_url = reverse_lazy("warehouse:product_list")

    def form_valid(self, form):
        messages.success(self.request, "Product updated.")
        return super().form_valid(form)


class ProductDeleteView(LoginRequiredMixin, AdminRequiredMixin, View):
    def post(self, request, pk):
        product = get_object_or_404(Product, pk=pk)
        try:
            product.delete()
            messages.success(request, f"Product '{product.name}' deleted.")
        except IntegrityError:
            messages.error(request, "Cannot delete — product has stock movements.")
        return redirect("warehouse:product_list")


# ── Distributor Product CRUD ────────────────────────────────────────────────


class DistributorProductListView(LoginRequiredMixin, AdminRequiredMixin, ListView):
    model = DistributorProduct
    template_name = "warehouse/distributor_product_list.html"
    context_object_name = "items"
    paginate_by = 50

    def get_queryset(self):
        qs = DistributorProduct.objects.select_related("distributor", "product")
        q = self.request.GET.get("q", "").strip()
        if q:
            qs = qs.filter(alias_sku__icontains=q) | qs.filter(alias_name__icontains=q) | qs.filter(product__name__icontains=q)
        distributor_id = self.request.GET.get("distributor", "").strip()
        if distributor_id:
            qs = qs.filter(distributor_id=distributor_id)
        return qs.order_by("distributor__name", "product__name")

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)

        ctx["distributors"] = Distributor.objects.filter(is_active=True).order_by("name")
        ctx["filter_distributor"] = self.request.GET.get("distributor", "")
        ctx["filter_q"] = self.request.GET.get("q", "")
        return ctx


class DistributorProductCreateView(LoginRequiredMixin, AdminRequiredMixin, CreateView):
    model = DistributorProduct
    form_class = DistributorProductForm
    template_name = "warehouse/distributor_product_form.html"
    success_url = reverse_lazy("warehouse:distributor_product_list")

    def form_valid(self, form):
        resp = super().form_valid(form)
        # Auto-create stock record with initial quantity
        initial_qty = form.cleaned_data.get("initial_quantity", 0) or 0
        stock, _ = DistributorStock.objects.get_or_create(
            distributor_product=self.object,
            defaults={"quantity": initial_qty},
        )
        if stock.quantity != initial_qty:
            stock.quantity = initial_qty
            stock.save(update_fields=["quantity"])
        messages.success(self.request, f"Product assigned to distributor. Initial stock: {initial_qty}")
        return resp


class DistributorProductEditView(LoginRequiredMixin, AdminRequiredMixin, UpdateView):
    model = DistributorProduct
    form_class = DistributorProductForm
    template_name = "warehouse/distributor_product_form.html"
    success_url = reverse_lazy("warehouse:distributor_product_list")

    def form_valid(self, form):
        messages.success(self.request, "Distributor product updated.")
        return super().form_valid(form)


class DistributorProductDeleteView(LoginRequiredMixin, AdminRequiredMixin, View):
    def post(self, request, pk):
        dp = get_object_or_404(DistributorProduct, pk=pk)
        try:
            dp.delete()
            messages.success(request, "Distributor product removed.")
        except IntegrityError:
            messages.error(request, "Cannot delete — has stock movements.")
        return redirect("warehouse:distributor_product_list")


# ── Distributor Stock ───────────────────────────────────────────────────────


class DistributorStockListView(LoginRequiredMixin, ListView):
    model = DistributorStock
    template_name = "warehouse/distributor_stock_list.html"
    context_object_name = "stocks"
    paginate_by = 50

    def get_queryset(self):
        user = self.request.user
        qs = DistributorStock.objects.select_related(
            "distributor_product__distributor",
            "distributor_product__product",
        )
        if not (user.is_admin or user.is_superuser):
            qs = qs.filter(distributor_product__distributor__in=get_user_distributors(user))

        q = self.request.GET.get("q", "").strip()
        if q:
            qs = qs.filter(distributor_product__product__name__icontains=q) | qs.filter(distributor_product__alias_name__icontains=q)
        distributor_id = self.request.GET.get("distributor", "").strip()
        if distributor_id:
            qs = qs.filter(distributor_product__distributor_id=distributor_id)
        return qs.order_by("distributor_product__distributor__name", "distributor_product__product__name")

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        user = self.request.user

        if user.is_admin or user.is_superuser:
            ctx["distributors"] = Distributor.objects.filter(is_active=True).order_by("name")
        else:
            ctx["distributors"] = get_user_distributors(user).order_by("name")
        ctx["filter_distributor"] = self.request.GET.get("distributor", "")
        ctx["filter_q"] = self.request.GET.get("q", "")
        return ctx


class DistributorStockAdjustView(LoginRequiredMixin, AdminRequiredMixin, View):
    template_name = "warehouse/stock_adjust.html"

    def get(self, request, pk):
        ds = get_object_or_404(DistributorStock.objects.select_related(
            "distributor_product__product", "distributor_product__distributor",
        ), pk=pk)
        form = StockAdjustForm()
        return render(request, self.template_name, {
            "form": form,
            "product": ds.distributor_product.product,
            "distributor": ds.distributor_product.distributor,
            "stock": ds,
            "stock_type": "distributor",
        })

    def post(self, request, pk):
        from django.db import transaction

        ds = get_object_or_404(DistributorStock.objects.select_related(
            "distributor_product__product", "distributor_product__distributor",
        ), pk=pk)
        form = StockAdjustForm(request.POST)
        if not form.is_valid():
            return render(request, self.template_name, {
                "form": form,
                "product": ds.distributor_product.product,
                "distributor": ds.distributor_product.distributor,
                "stock": ds,
                "stock_type": "distributor",
            })

        movement_type = form.cleaned_data["movement_type"]
        qty = form.cleaned_data["quantity"]
        note = form.cleaned_data.get("note", "")

        with transaction.atomic():
            ds = DistributorStock.objects.select_for_update().get(pk=pk)
            before = ds.quantity

            if movement_type == StockMovement.TYPE_IN:
                ds.quantity += qty
            else:  # ADJUST
                ds.quantity = qty

            ds.save()

            mb = MovementBatch.objects.create(
                code=MovementBatch.generate_code(),
                distributor=ds.distributor_product.distributor,
                movement_type=movement_type,
                total_quantity=qty,
                reference=f"Manual adjust — {ds.distributor_product.product.name}",
                created_by=request.user,
            )
            StockMovement.objects.create(
                movement_batch=mb,
                distributor_product=ds.distributor_product,
                movement_type=movement_type,
                quantity=qty,
                quantity_before=before,
                quantity_after=ds.quantity,
                note=note,
                created_by=request.user,
            )

        messages.success(request, f"Stock updated: {before} → {ds.quantity}")
        return redirect("warehouse:distributor_stock_list")


# ── Stock Movements ─────────────────────────────────────────────────────────


class MovementBatchListView(LoginRequiredMixin, ListView):
    """Grouped movement list — one row per MovementBatch."""
    model = MovementBatch
    template_name = "warehouse/movement_list.html"
    context_object_name = "batches"
    paginate_by = 50

    def get_queryset(self):
        user = self.request.user
        qs = MovementBatch.objects.select_related("distributor", "created_by")
        if not (user.is_admin or user.is_superuser):
            qs = qs.filter(distributor__in=get_user_distributors(user))

        distributor_id = self.request.GET.get("distributor", "").strip()
        if distributor_id:
            qs = qs.filter(distributor_id=distributor_id)
        movement_type = self.request.GET.get("type", "").strip()
        if movement_type:
            qs = qs.filter(movement_type=movement_type)
        return qs.order_by("-created_at")

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        user = self.request.user

        if user.is_admin or user.is_superuser:
            ctx["distributors"] = Distributor.objects.filter(is_active=True).order_by("name")
        else:
            ctx["distributors"] = get_user_distributors(user).order_by("name")
        ctx["filter_distributor"] = self.request.GET.get("distributor", "")
        ctx["filter_type"] = self.request.GET.get("type", "")
        return ctx


class MovementBatchDetailView(LoginRequiredMixin, ListView):
    """All movements within a MovementBatch."""
    model = StockMovement
    template_name = "warehouse/movement_detail.html"
    context_object_name = "movements"
    paginate_by = 100

    def get_queryset(self):
        self.batch = get_object_or_404(
            MovementBatch.objects.select_related("distributor", "created_by"),
            pk=self.kwargs["pk"],
        )
        return StockMovement.objects.filter(
            movement_batch=self.batch
        ).select_related(
            "distributor_product__product",
            "distributor_product__distributor",
        ).order_by("pk")

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["batch"] = self.batch
        return ctx


# ── Warehouse Config ────────────────────────────────────────────────────────


class NotificationView(LoginRequiredMixin, View):
    """Show low-stock alerts."""

    template_name = "warehouse/notifications.html"

    def get(self, request):
        from apps.warehouse.services.stock import get_low_stock_alerts
        alerts = get_low_stock_alerts(user=request.user)
        config = WarehouseFieldConfig.load()
        threshold = config.min_stock_threshold if config else 10
        return render(request, self.template_name, {
            "alerts": alerts,
            "threshold": threshold,
        })


class WarehouseConfigView(LoginRequiredMixin, AdminRequiredMixin, View):
    template_name = "warehouse/config.html"

    def get(self, request):
        config = WarehouseFieldConfig.load()
        form = WarehouseConfigForm(instance=config)
        return render(request, self.template_name, {"form": form})

    def post(self, request):
        config = WarehouseFieldConfig.load()
        form = WarehouseConfigForm(request.POST, instance=config)
        if form.is_valid():
            form.save()
            messages.success(request, "Warehouse configuration saved.")
            return redirect("warehouse:config")
        return render(request, self.template_name, {"form": form})

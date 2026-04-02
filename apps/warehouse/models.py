from django.conf import settings
from django.db import models


class Product(models.Model):
    """Master product catalog — admin-managed."""

    sku = models.CharField(max_length=50, unique=True)
    name = models.CharField(max_length=200)
    category = models.CharField(max_length=100, blank=True)
    unit = models.CharField(max_length=50, help_text="e.g. PCS, BOX, KG")
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return f"{self.sku} — {self.name}"


class MainStock(models.Model):
    """Stock in the main (central) warehouse. One row per product."""

    product = models.OneToOneField(
        Product, on_delete=models.CASCADE, related_name="main_stock"
    )
    quantity = models.IntegerField(default=0, help_text="Current stock quantity")
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.product.sku}: {self.quantity}"


class DistributorProduct(models.Model):
    """Product assigned to a distributor, with optional alias SKU/name."""

    distributor = models.ForeignKey(
        "distributors.Distributor",
        on_delete=models.CASCADE,
        related_name="warehouse_products",
    )
    product = models.ForeignKey(
        Product, on_delete=models.CASCADE, related_name="distributor_products"
    )
    alias_sku = models.CharField(
        max_length=50, blank=True,
        help_text="Distributor's own SKU for this product",
    )
    alias_name = models.CharField(
        max_length=200, blank=True,
        help_text="Distributor's own product name",
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("distributor", "product")
        indexes = [
            models.Index(fields=["distributor", "alias_sku"]),
            models.Index(fields=["distributor", "alias_name"]),
        ]

    def __str__(self):
        label = self.alias_name or self.product.name
        return f"{self.distributor.code}: {label}"


class DistributorStock(models.Model):
    """Stock per distributor per product. Quantity may go negative."""

    distributor_product = models.OneToOneField(
        DistributorProduct, on_delete=models.CASCADE, related_name="stock"
    )
    quantity = models.IntegerField(default=0, help_text="Current stock. Can be negative.")
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.distributor_product}: {self.quantity}"


class MovementBatch(models.Model):
    """Groups StockMovements created in a single approve/bulk action."""

    code = models.CharField(max_length=20, unique=True, help_text="Auto-generated MID-XXXXX")
    distributor = models.ForeignKey(
        "distributors.Distributor",
        on_delete=models.CASCADE,
        related_name="movement_batches",
    )
    movement_type = models.CharField(max_length=10, choices=[
        ("IN", "Stock In"), ("OUT", "Stock Out"), ("ADJUST", "Adjustment"),
    ])
    total_quantity = models.IntegerField(default=0)
    reference = models.CharField(max_length=255, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.code} — {self.distributor.name}"

    @classmethod
    def generate_code(cls):
        last = cls.objects.order_by("-pk").first()
        next_num = (last.pk + 1) if last else 1
        return f"MID-{next_num:05d}"


class StockMovement(models.Model):
    """Audit log for every stock change."""

    TYPE_IN = "IN"
    TYPE_OUT = "OUT"
    TYPE_ADJUST = "ADJUST"
    TYPE_CHOICES = [
        (TYPE_IN, "Stock In"),
        (TYPE_OUT, "Stock Out"),
        (TYPE_ADJUST, "Adjustment"),
    ]

    movement_batch = models.ForeignKey(
        MovementBatch,
        on_delete=models.CASCADE,
        null=True, blank=True,
        related_name="movements",
    )
    distributor_product = models.ForeignKey(
        DistributorProduct, on_delete=models.CASCADE, related_name="movements"
    )
    movement_type = models.CharField(max_length=10, choices=TYPE_CHOICES)
    quantity = models.IntegerField(help_text="Amount moved (always positive)")
    quantity_before = models.IntegerField()
    quantity_after = models.IntegerField()
    reference = models.CharField(
        max_length=255, blank=True,
        help_text="e.g. ProcessingRun #5 or Batch #12",
    )
    note = models.TextField(blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["distributor_product", "-created_at"]),
        ]

    def __str__(self):
        return f"{self.get_movement_type_display()} {self.quantity} — {self.distributor_product}"


class WarehouseFieldConfig(models.Model):
    """Singleton config: which StandardMasterField names map to product identifier and quantity."""

    product_identifier_field = models.CharField(
        max_length=100,
        help_text="StandardMasterField.name used as product identifier (e.g. 'item_name')",
    )
    quantity_field = models.CharField(
        max_length=100,
        blank=True,
        default="",
        help_text="StandardMasterField.name holding the quantity. Leave empty to use 1 per row.",
    )
    min_stock_threshold = models.IntegerField(
        default=10,
        help_text="Show notification when distributor stock falls to or below this value",
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Warehouse Field Configuration"

    def __str__(self):
        return f"Product={self.product_identifier_field}, Qty={self.quantity_field}"

    def save(self, *args, **kwargs):
        # Singleton: always overwrite pk=1
        self.pk = 1
        super().save(*args, **kwargs)

    @classmethod
    def load(cls):
        return cls.objects.filter(pk=1).first()

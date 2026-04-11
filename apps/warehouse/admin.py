from django.contrib import admin

from .models import (
    DistributorProduct,
    DistributorStock,
    Product,
    StockMovement,
    WarehouseFieldConfig,
)


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ["sku", "name", "category", "unit", "is_active"]
    search_fields = ["sku", "name"]
    list_filter = ["category", "is_active"]


@admin.register(DistributorProduct)
class DistributorProductAdmin(admin.ModelAdmin):
    list_display = ["distributor", "product", "alias_sku", "alias_name", "is_active"]
    list_filter = ["distributor", "is_active"]
    search_fields = ["alias_sku", "alias_name", "product__name", "product__sku"]


@admin.register(DistributorStock)
class DistributorStockAdmin(admin.ModelAdmin):
    list_display = ["distributor_product", "quantity", "updated_at"]


@admin.register(StockMovement)
class StockMovementAdmin(admin.ModelAdmin):
    list_display = ["distributor_product", "movement_type", "quantity", "quantity_before", "quantity_after", "created_at"]
    list_filter = ["movement_type"]


@admin.register(WarehouseFieldConfig)
class WarehouseFieldConfigAdmin(admin.ModelAdmin):
    list_display = ["product_identifier_field", "quantity_field", "updated_at"]

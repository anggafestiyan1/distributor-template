from django import forms

from .models import (
    DistributorProduct,
    Product,
    StockMovement,
    WarehouseFieldConfig,
)


class ProductForm(forms.ModelForm):
    class Meta:
        model = Product
        fields = ["sku", "name", "category", "unit", "description", "is_active"]
        widgets = {"description": forms.Textarea(attrs={"rows": 3})}


class DistributorProductForm(forms.ModelForm):
    class Meta:
        model = DistributorProduct
        fields = ["distributor", "product", "alias_sku", "alias_name", "is_active"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from apps.distributors.models import Distributor
        self.fields["distributor"].queryset = Distributor.objects.filter(is_active=True)
        self.fields["product"].queryset = Product.objects.filter(is_active=True)


class StockAdjustForm(forms.Form):
    MOVEMENT_CHOICES = [
        (StockMovement.TYPE_IN, "Stock In"),
        (StockMovement.TYPE_ADJUST, "Adjustment (set to exact value)"),
    ]

    movement_type = forms.ChoiceField(choices=MOVEMENT_CHOICES)
    quantity = forms.IntegerField(min_value=0, help_text="For 'Stock In': amount to add. For 'Adjustment': new absolute value.")
    note = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 2}))


class WarehouseConfigForm(forms.ModelForm):
    class Meta:
        model = WarehouseFieldConfig
        fields = ["product_identifier_field", "quantity_field", "min_stock_threshold"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from apps.field_templates.models import StandardMasterField
        field_choices = [("", "---------")] + [
            (sf.name, f"{sf.display_name} ({sf.name})")
            for sf in StandardMasterField.objects.order_by("order", "name")
        ]
        qty_choices = [("", "Default: 1 per row (no quantity column)")] + field_choices[1:]
        self.fields["product_identifier_field"].widget = forms.Select(choices=field_choices)
        self.fields["quantity_field"].widget = forms.Select(choices=qty_choices)
        self.fields["quantity_field"].required = False

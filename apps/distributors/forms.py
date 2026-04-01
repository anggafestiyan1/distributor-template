from django import forms
from .models import Area, Distributor, UserDistributorAssignment


class AreaForm(forms.ModelForm):
    class Meta:
        model = Area
        fields = ["name", "code", "description", "is_active"]
        widgets = {"description": forms.Textarea(attrs={"rows": 3})}


class DistributorForm(forms.ModelForm):
    class Meta:
        model = Distributor
        fields = ["name", "code", "area", "is_active", "notes"]
        widgets = {"notes": forms.Textarea(attrs={"rows": 3})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["area"].queryset = Area.objects.filter(is_active=True).order_by("name")


class AssignmentForm(forms.ModelForm):
    class Meta:
        model = UserDistributorAssignment
        fields = ["user", "distributor"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from apps.accounts.models import CustomUser
        self.fields["user"].queryset = CustomUser.objects.filter(
            is_active=True, role="distributor"
        ).order_by("username")
        self.fields["distributor"].queryset = Distributor.objects.filter(
            is_active=True
        ).select_related("area").order_by("name")

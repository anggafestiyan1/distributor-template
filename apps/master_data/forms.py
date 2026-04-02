from django import forms


class ExportForm(forms.Form):
    FORMAT_CHOICES = [("csv", "CSV"), ("xlsx", "Excel (.xlsx)")]

    format = forms.ChoiceField(choices=FORMAT_CHOICES, initial="csv")
    area = forms.ChoiceField(required=False, label="Area")
    distributor = forms.ModelChoiceField(
        queryset=None, required=False, empty_label="All distributors"
    )
    date_from = forms.DateField(required=False, widget=forms.DateInput(attrs={"type": "date"}))
    date_to = forms.DateField(required=False, widget=forms.DateInput(attrs={"type": "date"}))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from apps.distributors.models import Area, Distributor
        area_choices = [("", "All areas")] + [
            (a.name, a.name) for a in Area.objects.filter(is_active=True).order_by("name")
        ]
        self.fields["area"].choices = area_choices
        self.fields["distributor"].queryset = Distributor.objects.filter(is_active=True).order_by("name")

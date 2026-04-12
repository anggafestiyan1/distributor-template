from django import forms
from django.forms import inlineformset_factory

from .models import (
    HeaderFieldMapping, StandardMasterField,
    Template, TemplateFieldMapping, TemplateVersion,
)


class StandardMasterFieldForm(forms.ModelForm):
    class Meta:
        model = StandardMasterField
        fields = ["name", "display_name", "data_type", "is_displayed", "batch_context_source", "order", "description"]
        widgets = {"description": forms.Textarea(attrs={"rows": 3})}


class TemplateForm(forms.ModelForm):
    class Meta:
        model = Template
        fields = ["code", "name", "scope", "distributor", "description"]
        widgets = {"description": forms.Textarea(attrs={"rows": 3})}

    def clean(self):
        cleaned = super().clean()
        scope = cleaned.get("scope")
        distributor = cleaned.get("distributor")
        if scope == "assigned" and not distributor:
            self.add_error("distributor", "Assigned templates require a distributor.")
        if scope == "global" and distributor:
            self.add_error("distributor", "Global templates must not have a distributor.")
        return cleaned


class TemplateVersionForm(forms.ModelForm):
    class Meta:
        model = TemplateVersion
        fields = ["notes", "is_active"]
        widgets = {"notes": forms.Textarea(attrs={"rows": 3})}


class TemplateFieldMappingForm(forms.ModelForm):
    class Meta:
        model = TemplateFieldMapping
        fields = ["standard_field", "source_column"]


TemplateFieldMappingFormSet = inlineformset_factory(
    TemplateVersion,
    TemplateFieldMapping,
    form=TemplateFieldMappingForm,
    extra=0,
    can_delete=True,
    fields=["standard_field", "source_column"],
)


class HeaderFieldMappingForm(forms.ModelForm):
    class Meta:
        model = HeaderFieldMapping
        fields = ["standard_field", "label"]


HeaderFieldMappingFormSet = inlineformset_factory(
    TemplateVersion,
    HeaderFieldMapping,
    form=HeaderFieldMappingForm,
    extra=0,
    can_delete=True,
    fields=["standard_field", "label"],
)

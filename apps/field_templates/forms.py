from django import forms
from django.forms import BaseInlineFormSet, inlineformset_factory

from apps.field_templates.services.normalization import normalize_header
from .models import (
    FieldAlias, StandardMasterField,
    Template, TemplateFieldMapping, TemplateVersion,
)


class StandardMasterFieldForm(forms.ModelForm):
    class Meta:
        model = StandardMasterField
        fields = ["name", "display_name", "data_type", "is_displayed", "batch_context_source", "order", "description"]
        widgets = {"description": forms.Textarea(attrs={"rows": 3})}


class FieldAliasForm(forms.ModelForm):
    class Meta:
        model = FieldAlias
        fields = ["alias_original"]


class BaseFieldAliasFormSet(BaseInlineFormSet):
    """Validate that no two aliases normalize to the same value for this field."""

    def clean(self):
        super().clean()
        seen = {}
        for form in self.forms:
            if not form.cleaned_data or form.cleaned_data.get("DELETE"):
                continue
            raw = form.cleaned_data.get("alias_original", "").strip()
            if not raw:
                continue
            normalized = normalize_header(raw)
            if normalized in seen:
                raise forms.ValidationError(
                    f'Duplicate alias: "{raw}" normalizes to "{normalized}", '
                    f'same as "{seen[normalized]}".'
                )
            seen[normalized] = raw


FieldAliasFormSet = inlineformset_factory(
    StandardMasterField,
    FieldAlias,
    form=FieldAliasForm,
    formset=BaseFieldAliasFormSet,
    extra=0,
    can_delete=True,
    fields=["alias_original"],
)


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

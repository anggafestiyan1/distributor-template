import os
from django import forms
from django.conf import settings


ALLOWED_EXTENSIONS = getattr(settings, "ALLOWED_UPLOAD_EXTENSIONS", [".xlsx", ".csv"])


class MultiFileInput(forms.ClearableFileInput):
    """File input that allows selecting multiple files."""
    allow_multiple_selected = True


class MultiFileField(forms.FileField):
    """FileField that accepts multiple files."""
    def __init__(self, *args, **kwargs):
        kwargs.setdefault("widget", MultiFileInput(attrs={"multiple": True}))
        super().__init__(*args, **kwargs)

    def clean(self, data, initial=None):
        if isinstance(data, (list, tuple)):
            return [super(MultiFileField, self).clean(d, initial) for d in data]
        return [super().clean(data, initial)]


class UploadBatchForm(forms.Form):
    distributor = forms.ModelChoiceField(
        queryset=None,
        empty_label="Select distributor...",
    )
    files = MultiFileField(
        label="Files",
        help_text=f"Allowed formats: {', '.join(ALLOWED_EXTENSIONS)}. Max 50 MB per file. You can select multiple files.",
    )

    def __init__(self, *args, **kwargs):
        user = kwargs.pop("user", None)
        super().__init__(*args, **kwargs)
        from apps.distributors.models import get_user_distributors
        self.auto_distributor = None
        if user:
            distributor_qs = get_user_distributors(user)
            self.fields["distributor"].queryset = distributor_qs
            # For distributor users, auto-select their single assigned distributor
            if getattr(user, "is_distributor_user", False):
                assigned = list(distributor_qs)
                if len(assigned) == 1:
                    self.auto_distributor = assigned[0]
                    self.fields["distributor"].initial = assigned[0]
                    self.fields["distributor"].widget = forms.HiddenInput()

    def clean_files(self):
        uploaded_files = self.cleaned_data["files"]
        if not uploaded_files:
            raise forms.ValidationError("Please select at least one file.")

        max_size = getattr(settings, "FILE_UPLOAD_MAX_MEMORY_SIZE", 52428800)
        for uploaded in uploaded_files:
            ext = os.path.splitext(uploaded.name)[1].lower()
            if ext not in ALLOWED_EXTENSIONS:
                raise forms.ValidationError(
                    f"File '{uploaded.name}': type '{ext}' not allowed. "
                    f"Allowed: {', '.join(ALLOWED_EXTENSIONS)}"
                )
            if uploaded.size > max_size:
                raise forms.ValidationError(
                    f"File '{uploaded.name}' too large. Maximum size is {max_size // (1024*1024)} MB."
                )
        return uploaded_files


class ReprocessForm(forms.Form):
    reason = forms.CharField(
        max_length=500,
        widget=forms.Textarea(attrs={"rows": 3}),
        help_text="Explain why this batch is being reprocessed.",
    )

import os
from django import forms
from django.conf import settings


ALLOWED_EXTENSIONS = getattr(settings, "ALLOWED_UPLOAD_EXTENSIONS", [".xlsx", ".csv"])


class UploadBatchForm(forms.Form):
    distributor = forms.ModelChoiceField(
        queryset=None,
        empty_label="Select distributor...",
    )
    file = forms.FileField(
        help_text=f"Allowed formats: {', '.join(ALLOWED_EXTENSIONS)}. Max 50 MB.",
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

    def clean_file(self):
        uploaded = self.cleaned_data["file"]
        ext = os.path.splitext(uploaded.name)[1].lower()
        if ext not in ALLOWED_EXTENSIONS:
            raise forms.ValidationError(
                f"File type '{ext}' is not allowed. Allowed: {', '.join(ALLOWED_EXTENSIONS)}"
            )
        max_size = getattr(settings, "FILE_UPLOAD_MAX_MEMORY_SIZE", 52428800)
        if uploaded.size > max_size:
            raise forms.ValidationError(
                f"File too large. Maximum size is {max_size // (1024*1024)} MB."
            )
        return uploaded


class ReprocessForm(forms.Form):
    reason = forms.CharField(
        max_length=500,
        widget=forms.Textarea(attrs={"rows": 3}),
        help_text="Explain why this batch is being reprocessed.",
    )

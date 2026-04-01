from django import forms


class RowReviewForm(forms.Form):
    note = forms.CharField(
        required=False,
        max_length=500,
        widget=forms.Textarea(attrs={"rows": 2, "placeholder": "Optional note..."}),
    )

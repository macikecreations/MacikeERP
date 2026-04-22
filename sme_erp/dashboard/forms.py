from django import forms

from .models import AppSettings


class AppSettingsForm(forms.ModelForm):
    class Meta:
        model = AppSettings
        fields = [
            "business_name",
            "logo_url",
            "business_address",
            "business_phone",
            "business_email",
            "currency_code",
            "vat_rate",
            "invoice_terms",
            "receipt_footer",
            "theme",
            "compact_mode",
            "default_payment_method",
            "require_phone_for_mpesa",
            "auto_open_receipt",
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name, field in self.fields.items():
            field.widget.attrs["class"] = "form-check-input" if isinstance(field.widget, forms.CheckboxInput) else "form-control"

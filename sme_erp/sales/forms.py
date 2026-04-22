from django import forms

from dashboard.models import AppSettings
from inventory.models import Product
from .models import Customer, PaymentEntry, SalesInvoice


class QuickSaleForm(forms.Form):
    product = forms.ModelChoiceField(queryset=Product.objects.all())
    quantity = forms.IntegerField(min_value=1)
    payment_method = forms.ChoiceField(choices=SalesInvoice.PaymentMethod.choices)
    customer_name = forms.CharField(max_length=100, required=False, initial="Walk-in")
    phone_number = forms.CharField(max_length=15, required=False, help_text="Required for M-Pesa checkout.")

    def __init__(self, *args, **kwargs):
        settings_obj = kwargs.pop("settings_obj", None) or AppSettings.get_solo()
        super().__init__(*args, **kwargs)
        self.settings_obj = settings_obj
        self.fields["payment_method"].initial = settings_obj.default_payment_method
        for field in self.fields.values():
            field.widget.attrs["class"] = "form-control"

    def clean(self):
        cleaned = super().clean()
        payment_method = cleaned.get("payment_method")
        phone_number = (cleaned.get("phone_number") or "").strip()
        if payment_method == SalesInvoice.PaymentMethod.MPESA and self.settings_obj.require_phone_for_mpesa and not phone_number:
            self.add_error("phone_number", "Phone number is required for M-Pesa checkout.")
        return cleaned


class PaymentEntryForm(forms.ModelForm):
    class Meta:
        model = PaymentEntry
        fields = ["method", "amount", "reference", "notes", "status"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs["class"] = "form-control"


class CustomerForm(forms.ModelForm):
    class Meta:
        model = Customer
        fields = ["name", "mobile", "address", "region", "is_active"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name, field in self.fields.items():
            field.widget.attrs["class"] = "form-check-input" if name == "is_active" else "form-control"

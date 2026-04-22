from django import forms

from inventory.models import Product
from .models import SalesInvoice


class QuickSaleForm(forms.Form):
    product = forms.ModelChoiceField(queryset=Product.objects.all())
    quantity = forms.IntegerField(min_value=1)
    payment_method = forms.ChoiceField(choices=SalesInvoice.PaymentMethod.choices)
    customer_name = forms.CharField(max_length=100, required=False, initial="Walk-in")
    phone_number = forms.CharField(max_length=15, required=False, help_text="Required for M-Pesa checkout.")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs["class"] = "form-control"

    def clean(self):
        cleaned = super().clean()
        payment_method = cleaned.get("payment_method")
        phone_number = (cleaned.get("phone_number") or "").strip()
        if payment_method == SalesInvoice.PaymentMethod.MPESA and not phone_number:
            self.add_error("phone_number", "Phone number is required for M-Pesa checkout.")
        return cleaned

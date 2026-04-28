from decimal import Decimal

from django import forms

from dashboard.models import AppSettings
from inventory.models import Product
from .models import Customer, PaymentEntry, SalesInvoice
from .mpesa import normalize_msisdn_for_daraja


class QuickSaleForm(forms.Form):
    product = forms.ModelChoiceField(queryset=Product.objects.all())
    quantity = forms.IntegerField(min_value=1)
    customer_name = forms.CharField(
        max_length=100,
        required=True,
        label="Customer name",
    )
    customer_address = forms.CharField(
        max_length=255,
        required=False,
        label="Customer address",
        help_text="Required when paying by card.",
    )
    customer_region = forms.CharField(
        max_length=120,
        required=False,
        label="Customer region",
        help_text="Required when paying by card.",
    )
    phone_number = forms.CharField(
        max_length=20,
        required=False,
        label="Phone number",
        help_text="Optional. Required for M-Pesa checkout when enabled in Settings.",
    )
    discount_kes = forms.DecimalField(
        required=False,
        min_value=Decimal("0"),
        max_digits=12,
        decimal_places=2,
        initial=Decimal("0"),
        label="Discount (KES)",
        help_text="Leave 0 for no discount. Filling KES or % updates the other automatically.",
    )
    discount_percent = forms.DecimalField(
        required=False,
        min_value=Decimal("0"),
        max_digits=7,
        decimal_places=2,
        initial=Decimal("0"),
        label="Discount (%)",
        help_text="Percent of line subtotal before VAT. Cleared if you only use KES.",
    )
    payment_method = forms.ChoiceField(choices=SalesInvoice.PaymentMethod.choices)

    def __init__(self, *args, **kwargs):
        settings_obj = kwargs.pop("settings_obj", None) or AppSettings.get_solo()
        super().__init__(*args, **kwargs)
        self.settings_obj = settings_obj
        self.fields["payment_method"].initial = settings_obj.default_payment_method
        for name, field in self.fields.items():
            field.widget.attrs["class"] = "form-control"
            if name in ("discount_kes", "discount_percent"):
                field.widget.attrs["step"] = "0.01"
                field.widget.attrs["min"] = "0"

    def clean(self):
        cleaned = super().clean()
        payment_method = cleaned.get("payment_method")
        phone_raw = (cleaned.get("phone_number") or "").strip()
        product = cleaned.get("product")
        qty = cleaned.get("quantity")

        if payment_method == SalesInvoice.PaymentMethod.CARD:
            addr = (cleaned.get("customer_address") or "").strip()
            reg = (cleaned.get("customer_region") or "").strip()
            if not addr:
                self.add_error("customer_address", "Address is required for card payments.")
            if not reg:
                self.add_error("customer_region", "Region is required for card payments.")

        if payment_method == SalesInvoice.PaymentMethod.MPESA:
            if self.settings_obj.require_phone_for_mpesa and not phone_raw:
                self.add_error("phone_number", "Phone number is required for M-Pesa checkout.")
            elif phone_raw:
                try:
                    cleaned["phone_number"] = normalize_msisdn_for_daraja(phone_raw)
                except ValueError as exc:
                    self.add_error("phone_number", str(exc))
        elif phone_raw:
            try:
                cleaned["phone_number"] = normalize_msisdn_for_daraja(phone_raw)
            except ValueError as exc:
                self.add_error("phone_number", str(exc))

        if product and qty is not None:
            gross = Decimal(qty) * Decimal(str(product.selling_price))
            dk = cleaned.get("discount_kes")
            dp = cleaned.get("discount_percent")
            dk = Decimal("0") if dk in (None, "") else Decimal(str(dk)).quantize(Decimal("0.01"))
            dp = Decimal("0") if dp in (None, "") else Decimal(str(dp)).quantize(Decimal("0.01"))
            if dk > 0 and dp > 0:
                dp = (dk / gross * Decimal("100")).quantize(Decimal("0.01")) if gross > 0 else Decimal("0")
            elif dp > 0:
                dk = (gross * dp / Decimal("100")).quantize(Decimal("0.01"))
            elif dk > 0 and gross > 0:
                dp = (dk / gross * Decimal("100")).quantize(Decimal("0.01"))
            if dk > gross:
                self.add_error("discount_kes", "Discount cannot exceed the line subtotal (qty × unit price).")
                return cleaned
            cleaned["discount_kes"] = dk
            cleaned["discount_percent"] = dp

        return cleaned


class PaymentEntryForm(forms.ModelForm):
    class Meta:
        model = PaymentEntry
        fields = ["method", "amount", "reference", "notes", "status"]

    def __init__(self, *args, invoice=None, **kwargs):
        super().__init__(*args, **kwargs)
        for name, field in self.fields.items():
            field.widget.attrs["class"] = "form-control"
            if name == "amount":
                field.widget.attrs.setdefault("step", "0.01")
                field.widget.attrs.setdefault("min", "0")
        if invoice and not self.is_bound:
            total_paid = sum(
                (e.amount for e in invoice.payment_entries.filter(status=PaymentEntry.Status.POSTED)),
                Decimal("0"),
            )
            balance = (invoice.total_amount - total_paid).quantize(Decimal("0.01"))
            if balance < 0:
                balance = Decimal("0.00")
            self.fields["amount"].initial = balance
            pm = invoice.payment_method
            if pm in {c[0] for c in PaymentEntry.Method.choices}:
                self.fields["method"].initial = pm
            self.fields["reference"].initial = f"INV-{invoice.id}"
            self.fields["notes"].initial = (
                f"Invoice INV-{invoice.id} — {invoice.get_payment_method_display()} — balance payment."
            )


class CustomerForm(forms.ModelForm):
    class Meta:
        model = Customer
        fields = ["name", "mobile", "address", "region", "is_active"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name, field in self.fields.items():
            field.widget.attrs["class"] = "form-check-input" if name == "is_active" else "form-control"

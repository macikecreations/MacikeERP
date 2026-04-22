from decimal import Decimal

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models
from django.utils import timezone

from inventory.models import Product


class Customer(models.Model):
    name = models.CharField(max_length=120)
    mobile = models.CharField(max_length=20, blank=True)
    address = models.CharField(max_length=255, blank=True)
    region = models.CharField(max_length=120, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class SalesInvoice(models.Model):
    class Status(models.TextChoices):
        PENDING_PAYMENT = "PENDING_PAYMENT", "Pending Payment"
        PAID = "PAID", "Paid"
        FAILED = "FAILED", "Failed"

    class PaymentMethod(models.TextChoices):
        CASH = "CASH", "Cash"
        MPESA = "MPESA", "M-Pesa"
        CARD = "CARD", "Card"

    cashier = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="invoices")
    customer = models.ForeignKey(Customer, on_delete=models.SET_NULL, null=True, blank=True, related_name="invoices")
    customer_name = models.CharField(max_length=100, default="Walk-in")
    total_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    tax_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    payment_method = models.CharField(max_length=20, choices=PaymentMethod.choices, default=PaymentMethod.CASH)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PAID)
    due_date = models.DateField(default=timezone.localdate)
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-timestamp"]

    def __str__(self) -> str:
        return f"INV-{self.id or 'NEW'}"

    def recalculate_totals(self) -> None:
        subtotal = sum((line.subtotal for line in self.line_items.all()), Decimal("0.00"))
        self.tax_amount = (subtotal * Decimal("0.16")).quantize(Decimal("0.01"))
        self.total_amount = (subtotal + self.tax_amount).quantize(Decimal("0.01"))
        self.save(update_fields=["tax_amount", "total_amount"])


class SalesLineItem(models.Model):
    invoice = models.ForeignKey(SalesInvoice, on_delete=models.CASCADE, related_name="line_items")
    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name="sales_lines")
    quantity = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    unit_price = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(0)])
    subtotal = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(0)])


class MpesaTransaction(models.Model):
    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        COMPLETED = "COMPLETED", "Completed"
        FAILED = "FAILED", "Failed"

    invoice = models.ForeignKey(SalesInvoice, on_delete=models.PROTECT, related_name="mpesa_transactions")
    mpesa_code = models.CharField(max_length=20, unique=True, blank=True, null=True)
    merchant_request_id = models.CharField(max_length=100, blank=True, null=True)
    checkout_request_id = models.CharField(max_length=100, unique=True, blank=True, null=True)
    phone_number = models.CharField(max_length=15)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    result_desc = models.CharField(max_length=255, blank=True)
    raw_callback = models.JSONField(blank=True, null=True)


class PaymentEntry(models.Model):
    class Method(models.TextChoices):
        CASH = "CASH", "Cash"
        MPESA = "MPESA", "M-Pesa"
        CARD = "CARD", "Card"
        BANK = "BANK", "Bank Transfer"

    class Status(models.TextChoices):
        POSTED = "POSTED", "Posted"
        PENDING = "PENDING", "Pending"

    invoice = models.ForeignKey(SalesInvoice, on_delete=models.CASCADE, related_name="payment_entries")
    method = models.CharField(max_length=20, choices=Method.choices)
    amount = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(0)])
    reference = models.CharField(max_length=100, blank=True)
    notes = models.CharField(max_length=255, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.POSTED)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="payment_entries")
    created_at = models.DateTimeField(auto_now_add=True)

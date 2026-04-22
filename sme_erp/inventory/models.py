from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models


class ProductCategory(models.Model):
    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)

    def __str__(self) -> str:
        return self.name


class Supplier(models.Model):
    company_name = models.CharField(max_length=200, unique=True)
    contact_person = models.CharField(max_length=100)
    email = models.EmailField(unique=True, blank=True, null=True)
    phone = models.CharField(max_length=20)
    kra_pin = models.CharField(max_length=20, blank=True, null=True)

    def __str__(self) -> str:
        return self.company_name


class Product(models.Model):
    category = models.ForeignKey(ProductCategory, on_delete=models.PROTECT, related_name="products")
    supplier = models.ForeignKey(Supplier, on_delete=models.SET_NULL, blank=True, null=True, related_name="products")
    name = models.CharField(max_length=200)
    sku = models.CharField(max_length=50, unique=True)
    cost_price = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(0)])
    selling_price = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(0)])
    quantity = models.PositiveIntegerField(default=0)
    reorder_level = models.PositiveIntegerField(default=10)

    def __str__(self) -> str:
        return f"{self.name} ({self.sku})"

    @property
    def is_low_stock(self) -> bool:
        return self.quantity <= self.reorder_level


class StockBatch(models.Model):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="batches")
    quantity_received = models.PositiveIntegerField()
    quantity_remaining = models.PositiveIntegerField()
    unit_cost = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(0)])
    received_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["received_at", "id"]


class StockAuditLog(models.Model):
    class ActionType(models.TextChoices):
        RESTOCK = "RESTOCK", "Restock"
        SALE = "SALE", "Sale"
        RETURN = "RETURN", "Return"
        DAMAGE = "DAMAGE", "Damage"

    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name="audit_logs")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="stock_actions")
    action_type = models.CharField(max_length=10, choices=ActionType.choices)
    quantity_changed = models.IntegerField()
    remarks = models.TextField(blank=True)
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-timestamp"]

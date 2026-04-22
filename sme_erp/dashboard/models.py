from django.db import models


class AppSettings(models.Model):
    class ThemeChoice(models.TextChoices):
        LIGHT = "light", "Light"
        DARK = "dark", "Dark"
        SYSTEM = "system", "System"

    business_name = models.CharField(max_length=120, default="Macike Enterprise")
    logo_url = models.CharField(max_length=255, blank=True, help_text="Set a web/static path e.g. /static/img/macike-logo.png")
    business_address = models.CharField(max_length=255, blank=True, default="Mombasa, Kenya")
    business_phone = models.CharField(max_length=40, blank=True, default="")
    business_email = models.EmailField(blank=True, default="")
    currency_code = models.CharField(max_length=10, default="KES")
    vat_rate = models.DecimalField(max_digits=5, decimal_places=2, default=16.00)
    invoice_terms = models.CharField(max_length=255, default="Pay via M-Pesa. Payment due within 5 days.")
    receipt_footer = models.CharField(max_length=255, default="Thank you for shopping with Macike Enterprise.")
    theme = models.CharField(max_length=10, choices=ThemeChoice.choices, default=ThemeChoice.LIGHT)
    compact_mode = models.BooleanField(default=False)
    default_payment_method = models.CharField(max_length=20, default="CASH")
    require_phone_for_mpesa = models.BooleanField(default=True)
    auto_open_receipt = models.BooleanField(default=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return "Application Settings"

    @classmethod
    def get_solo(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj


class UserPageVisit(models.Model):
    user = models.ForeignKey("accounts.CustomUser", on_delete=models.CASCADE, related_name="page_visits")
    path = models.CharField(max_length=255)
    label = models.CharField(max_length=100)
    count = models.PositiveIntegerField(default=0)
    last_visited = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("user", "path")
        ordering = ["-count", "-last_visited"]

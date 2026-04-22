from django.contrib.auth.models import AbstractUser
from django.db import models


class CustomUser(AbstractUser):
    class Roles(models.TextChoices):
        ADMIN = "ADMIN", "Administrator"
        MANAGER = "MANAGER", "Manager"
        CASHIER = "CASHIER", "Cashier"
        AUDITOR = "AUDITOR", "Auditor"

    role = models.CharField(max_length=20, choices=Roles.choices, default=Roles.CASHIER)
    phone_number = models.CharField(max_length=15, blank=True, null=True)

    def save(self, *args, **kwargs):
        # Keep superusers mapped to admin role for RBAC checks.
        if self.is_superuser and self.role == self.Roles.CASHIER:
            self.role = self.Roles.ADMIN
        super().save(*args, **kwargs)

    def is_admin_or_manager(self) -> bool:
        return self.is_superuser or self.role in {self.Roles.ADMIN, self.Roles.MANAGER}

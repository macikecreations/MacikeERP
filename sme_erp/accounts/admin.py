from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import CustomUser


@admin.register(CustomUser)
class CustomUserAdmin(UserAdmin):
    fieldsets = UserAdmin.fieldsets + (
        ("ERP", {"fields": ("role", "phone_number")}),
    )
    list_display = ("username", "email", "role", "is_staff", "is_active")
from django.contrib import admin


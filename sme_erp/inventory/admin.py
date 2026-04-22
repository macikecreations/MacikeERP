from django.contrib import admin

from .models import Product, ProductCategory, StockAuditLog, StockBatch, Supplier

admin.site.register(ProductCategory)
admin.site.register(Supplier)
admin.site.register(Product)
admin.site.register(StockBatch)
admin.site.register(StockAuditLog)
from django.contrib import admin

# Register your models here.

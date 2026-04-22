from django.contrib import admin

from .models import MpesaTransaction, SalesInvoice, SalesLineItem

admin.site.register(SalesInvoice)
admin.site.register(SalesLineItem)
admin.site.register(MpesaTransaction)
from django.contrib import admin

# Register your models here.

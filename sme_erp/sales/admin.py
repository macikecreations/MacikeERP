from django.contrib import admin

from .models import MpesaTransaction, PaymentEntry, SalesInvoice, SalesLineItem

admin.site.register(SalesInvoice)
admin.site.register(SalesLineItem)
admin.site.register(MpesaTransaction)
admin.site.register(PaymentEntry)

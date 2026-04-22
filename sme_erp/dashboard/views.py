import csv

from django.contrib.auth.decorators import login_required
from django.db import models
from django.http import HttpResponse
from django.shortcuts import render

from accounts.permissions import role_required
from inventory.models import Product, StockAuditLog
from sales.models import SalesInvoice


@login_required
@role_required("ADMIN", "MANAGER", "AUDITOR", "CASHIER")
def home(request):
    invoices_today = SalesInvoice.objects.count()
    low_stock_qs = Product.objects.filter(quantity__lte=models.F("reorder_level"))
    recent_sales = SalesInvoice.objects.select_related("cashier")[:8]
    recent_activity = StockAuditLog.objects.select_related("product", "user")[:8]
    context = {
        "product_count": Product.objects.count(),
        "invoice_count": invoices_today,
        "low_stock_count": low_stock_qs.count(),
        "low_stock_items": low_stock_qs[:10],
        "recent_sales": recent_sales,
        "recent_activity": recent_activity,
    }
    return render(request, "dashboard/home.html", context)


@login_required
@role_required("ADMIN", "MANAGER", "AUDITOR")
def export_backup_csv(request):
    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = 'attachment; filename="erp_backup_products.csv"'
    writer = csv.writer(response)
    writer.writerow(["id", "sku", "name", "cost_price", "selling_price", "quantity", "reorder_level"])
    for p in Product.objects.all().order_by("id"):
        writer.writerow([p.id, p.sku, p.name, p.cost_price, p.selling_price, p.quantity, p.reorder_level])
    return response

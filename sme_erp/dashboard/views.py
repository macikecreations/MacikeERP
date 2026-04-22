import csv
from datetime import timedelta

from django.contrib.auth.decorators import login_required
from django.db import models
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.utils import timezone

from accounts.permissions import role_required
from inventory.models import Product, StockAuditLog
from sales.models import SalesInvoice, SalesLineItem
from .forms import AppSettingsForm
from .models import AppSettings, UserPageVisit


@login_required
@role_required("ADMIN", "MANAGER", "AUDITOR", "CASHIER")
def home(request):
    invoices_today = SalesInvoice.objects.count()
    today = timezone.localdate()
    day_labels = []
    sales_series = []
    for i in range(6, -1, -1):
        day = today - timedelta(days=i)
        day_labels.append(day.strftime("%d %b"))
        total = (
            SalesInvoice.objects.filter(timestamp__date=day, status=SalesInvoice.Status.PAID)
            .aggregate(total=models.Sum("total_amount"))["total"]
            or 0
        )
        sales_series.append(float(total))

    payment_rows = (
        SalesInvoice.objects.filter(status=SalesInvoice.Status.PAID)
        .values("payment_method")
        .annotate(total=models.Sum("total_amount"))
        .order_by("payment_method")
    )
    payment_map = dict(SalesInvoice.PaymentMethod.choices)
    payment_labels = [payment_map.get(row["payment_method"], row["payment_method"]) for row in payment_rows]
    payment_values = [float(row["total"] or 0) for row in payment_rows]

    top_products = (
        SalesLineItem.objects.values("product__name")
        .annotate(total_qty=models.Sum("quantity"))
        .order_by("-total_qty")[:5]
    )
    top_product_labels = [row["product__name"] for row in top_products]
    top_product_values = [int(row["total_qty"]) for row in top_products]

    low_stock_qs = Product.objects.filter(quantity__lte=models.F("reorder_level"))
    recent_sales = SalesInvoice.objects.select_related("cashier")[:8]
    recent_activity = StockAuditLog.objects.select_related("product", "user")[:8]
    context = {
        "settings_obj": AppSettings.get_solo(),
        "product_count": Product.objects.count(),
        "invoice_count": invoices_today,
        "low_stock_count": low_stock_qs.count(),
        "low_stock_items": low_stock_qs[:10],
        "recent_sales": recent_sales,
        "recent_activity": recent_activity,
        "frequent_pages": UserPageVisit.objects.filter(user=request.user)[:6],
        "sales_labels": day_labels,
        "sales_series": sales_series,
        "payment_labels": payment_labels,
        "payment_values": payment_values,
        "top_product_labels": top_product_labels,
        "top_product_values": top_product_values,
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


@login_required
@role_required("ADMIN", "MANAGER")
def settings_view(request):
    settings_obj = AppSettings.get_solo()
    form = AppSettingsForm(request.POST or None, instance=settings_obj)
    if request.method == "POST" and form.is_valid():
        form.save()
        return redirect("dashboard-settings")
    return render(request, "dashboard/settings.html", {"form": form})

from django.urls import path

from .views import mpesa_callback, quick_sale, receipt_pdf, receipt_view, sales_report

urlpatterns = [
    path("pos/", quick_sale, name="sales-pos"),
    path("receipt/<int:invoice_id>/", receipt_view, name="sales-receipt"),
    path("receipt/<int:invoice_id>/pdf/", receipt_pdf, name="sales-receipt-pdf"),
    path("report/", sales_report, name="sales-report"),
    path("mpesa/callback/", mpesa_callback, name="mpesa-callback"),
]

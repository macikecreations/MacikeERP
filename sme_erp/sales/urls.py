from django.urls import path

from .views import (
    add_payment_entry,
    customer_create,
    customer_list,
    mpesa_callback,
    mpesa_status,
    quick_sale,
    receipt_pdf,
    receipt_view,
    sales_report,
)

urlpatterns = [
    path("pos/", quick_sale, name="sales-pos"),
    path("customers/", customer_list, name="sales-customers"),
    path("customers/new/", customer_create, name="sales-customer-create"),
    path("receipt/<int:invoice_id>/", receipt_view, name="sales-receipt"),
    path("receipt/<int:invoice_id>/payments/new/", add_payment_entry, name="sales-add-payment-entry"),
    path("receipt/<int:invoice_id>/pdf/", receipt_pdf, name="sales-receipt-pdf"),
    path("report/", sales_report, name="sales-report"),
    path("mpesa/callback/", mpesa_callback, name="mpesa-callback"),
    path("mpesa/status/", mpesa_status, name="mpesa-status"),
]

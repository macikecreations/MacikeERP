from datetime import timedelta
from decimal import Decimal
from io import BytesIO

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import models, transaction
from django.http import FileResponse, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

from accounts.permissions import role_required
from dashboard.models import AppSettings
from inventory.services import consume_fifo_stock
from .forms import CustomerForm, PaymentEntryForm, QuickSaleForm
from .models import Customer, MpesaTransaction, PaymentEntry, SalesInvoice, SalesLineItem
from .mpesa import MpesaConfigError, initiate_stk_push


def _finalize_invoice_stock(invoice: SalesInvoice) -> None:
    for line in invoice.line_items.select_related("product"):
        if line.quantity > line.product.quantity:
            raise ValueError(f"Insufficient stock for {line.product.name}.")
    for line in invoice.line_items.select_related("product"):
        consume_fifo_stock(
            product=line.product,
            quantity=line.quantity,
            user=invoice.cashier,
            remarks=f"Sale invoice INV-{invoice.id}",
        )


ONES = [
    "Zero", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine", "Ten",
    "Eleven", "Twelve", "Thirteen", "Fourteen", "Fifteen", "Sixteen", "Seventeen", "Eighteen", "Nineteen",
]
TENS = ["", "", "Twenty", "Thirty", "Forty", "Fifty", "Sixty", "Seventy", "Eighty", "Ninety"]


def _num_to_words(n: int) -> str:
    if n < 20:
        return ONES[n]
    if n < 100:
        return TENS[n // 10] + (f" {ONES[n % 10]}" if n % 10 else "")
    if n < 1000:
        return ONES[n // 100] + " Hundred" + (f" {_num_to_words(n % 100)}" if n % 100 else "")
    if n < 1_000_000:
        return _num_to_words(n // 1000) + " Thousand" + (f" {_num_to_words(n % 1000)}" if n % 1000 else "")
    return str(n)


@login_required
@role_required("ADMIN", "MANAGER", "CASHIER")
def quick_sale(request):
    app_settings = AppSettings.get_solo()
    form = QuickSaleForm(request.POST or None, settings_obj=app_settings)
    if request.method == "POST" and form.is_valid():
        product = form.cleaned_data["product"]
        quantity = form.cleaned_data["quantity"]
        payment_method = form.cleaned_data["payment_method"]
        customer_name = form.cleaned_data["customer_name"] or "Walk-in"
        phone_number = (form.cleaned_data.get("phone_number") or "").strip()

        if quantity > product.quantity:
            messages.error(request, "Insufficient stock quantity.")
            return redirect("sales-pos")

        if payment_method == SalesInvoice.PaymentMethod.MPESA:
            try:
                with transaction.atomic():
                    customer_obj = None
                    if customer_name and customer_name.lower() != "walk-in":
                        customer_obj, _ = Customer.objects.get_or_create(name=customer_name)
                    invoice = SalesInvoice.objects.create(
                        cashier=request.user,
                        customer=customer_obj,
                        customer_name=customer_name,
                        payment_method=payment_method,
                        status=SalesInvoice.Status.PENDING_PAYMENT,
                        due_date=timezone.localdate() + timedelta(days=5),
                    )
                    subtotal = Decimal(quantity) * product.selling_price
                    SalesLineItem.objects.create(
                        invoice=invoice,
                        product=product,
                        quantity=quantity,
                        unit_price=product.selling_price,
                        subtotal=subtotal,
                    )
                    invoice.recalculate_totals()

                    stk_response = initiate_stk_push(
                        phone_number=phone_number,
                        amount=int(invoice.total_amount),
                        account_reference=f"INV-{invoice.id}",
                        transaction_desc="Macike Enterprise ERP Sale",
                    )
                    MpesaTransaction.objects.create(
                        invoice=invoice,
                        checkout_request_id=stk_response.get("CheckoutRequestID", f"INV-{invoice.id}-{timezone.now().timestamp()}"),
                        merchant_request_id=stk_response.get("MerchantRequestID"),
                        phone_number=phone_number,
                        amount=invoice.total_amount,
                        status=MpesaTransaction.Status.PENDING,
                        result_desc=stk_response.get("CustomerMessage", "STK initiated"),
                        raw_callback=stk_response,
                    )
            except MpesaConfigError as exc:
                messages.error(request, str(exc))
                return redirect("sales-pos")
            except Exception as exc:
                messages.error(request, f"Unable to initiate STK push: {exc}")
                return redirect("sales-pos")

            messages.success(request, f"STK pushed to {phone_number}. Complete payment, then wait for callback confirmation.")
            if app_settings.auto_open_receipt:
                return redirect("sales-receipt", invoice_id=invoice.id)
            return redirect("sales-pos")
        else:
            try:
                with transaction.atomic():
                    customer_obj = None
                    if customer_name and customer_name.lower() != "walk-in":
                        customer_obj, _ = Customer.objects.get_or_create(name=customer_name)
                    invoice = SalesInvoice.objects.create(
                        cashier=request.user,
                        customer=customer_obj,
                        customer_name=customer_name,
                        payment_method=payment_method,
                        status=SalesInvoice.Status.PAID,
                        due_date=timezone.localdate(),
                    )
                    subtotal = Decimal(quantity) * product.selling_price
                    SalesLineItem.objects.create(
                        invoice=invoice,
                        product=product,
                        quantity=quantity,
                        unit_price=product.selling_price,
                        subtotal=subtotal,
                    )
                    invoice.recalculate_totals()
                    _finalize_invoice_stock(invoice)
            except ValueError as exc:
                messages.error(request, str(exc))
                messages.warning(request, "Restock this product first to create FIFO batches.")
                return redirect("sales-pos")

        messages.success(request, f"Sale processed. Invoice INV-{invoice.id}.")
        if app_settings.auto_open_receipt:
            return redirect("sales-receipt", invoice_id=invoice.id)
        return redirect("sales-pos")
    return render(request, "sales/pos.html", {"form": form})


@csrf_exempt
@require_POST
def mpesa_callback(request):
    payload = request.json if hasattr(request, "json") else None
    if payload is None:
        import json
        payload = json.loads(request.body.decode("utf-8") or "{}")

    stk = payload.get("Body", {}).get("stkCallback", {})
    checkout_request_id = stk.get("CheckoutRequestID")
    result_code = stk.get("ResultCode")
    result_desc = stk.get("ResultDesc", "")

    if not checkout_request_id:
        return HttpResponse("Missing CheckoutRequestID", status=400)

    try:
        with transaction.atomic():
            mpesa_txn = MpesaTransaction.objects.select_for_update().select_related("invoice").get(checkout_request_id=checkout_request_id)
            invoice = mpesa_txn.invoice
            if mpesa_txn.status == MpesaTransaction.Status.COMPLETED:
                return HttpResponse("OK", status=200)

            mpesa_txn.result_desc = result_desc
            mpesa_txn.raw_callback = payload

            if result_code == 0:
                items = stk.get("CallbackMetadata", {}).get("Item", [])
                item_map = {item.get("Name"): item.get("Value") for item in items}
                mpesa_txn.mpesa_code = item_map.get("MpesaReceiptNumber", mpesa_txn.mpesa_code)
                mpesa_txn.status = MpesaTransaction.Status.COMPLETED
                mpesa_txn.save(update_fields=["mpesa_code", "status", "result_desc", "raw_callback"])

                _finalize_invoice_stock(invoice)
                invoice.status = SalesInvoice.Status.PAID
                invoice.save(update_fields=["status"])
            else:
                mpesa_txn.status = MpesaTransaction.Status.FAILED
                mpesa_txn.save(update_fields=["status", "result_desc", "raw_callback"])
                invoice.status = SalesInvoice.Status.FAILED
                invoice.save(update_fields=["status"])
    except MpesaTransaction.DoesNotExist:
        return HttpResponse("Unknown transaction", status=404)
    except ValueError as exc:
        return HttpResponse(f"Stock finalization failed: {exc}", status=409)

    return HttpResponse("OK", status=200)


@login_required
@role_required("ADMIN", "MANAGER", "CASHIER", "AUDITOR")
def receipt_view(request, invoice_id: int):
    invoice = get_object_or_404(SalesInvoice.objects.select_related("cashier"), id=invoice_id)
    subtotal_amount = sum((line.subtotal for line in invoice.line_items.all()), Decimal("0.00"))
    mpesa_entries = invoice.mpesa_transactions.all().order_by("-id")
    payment_entries = invoice.payment_entries.select_related("created_by").order_by("-created_at")
    total_paid = sum((entry.amount for entry in payment_entries), Decimal("0.00"))
    amount_words = _num_to_words(int(invoice.total_amount))
    return render(
        request,
        "sales/receipt.html",
        {
            "invoice": invoice,
            "subtotal_amount": subtotal_amount,
            "mpesa_entries": mpesa_entries,
            "payment_entries": payment_entries,
            "total_paid": total_paid,
            "balance_due": invoice.total_amount - total_paid,
            "amount_words": amount_words,
        },
    )


@login_required
@role_required("ADMIN", "MANAGER", "CASHIER")
def add_payment_entry(request, invoice_id: int):
    invoice = get_object_or_404(SalesInvoice, id=invoice_id)
    form = PaymentEntryForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        entry = form.save(commit=False)
        entry.invoice = invoice
        entry.created_by = request.user
        entry.save()
        messages.success(request, "Payment entry added.")
        return redirect("sales-receipt", invoice_id=invoice.id)
    return render(request, "sales/payment_entry_form.html", {"invoice": invoice, "form": form})


@login_required
@role_required("ADMIN", "MANAGER", "CASHIER", "AUDITOR")
def customer_list(request):
    customers = Customer.objects.all().order_by("name")
    return render(request, "sales/customer_list.html", {"customers": customers})


@login_required
@role_required("ADMIN", "MANAGER", "CASHIER")
def customer_create(request):
    form = CustomerForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Customer saved.")
        return redirect("sales-customers")
    return render(request, "sales/customer_form.html", {"form": form})


@login_required
@role_required("ADMIN", "MANAGER", "CASHIER", "AUDITOR")
def receipt_pdf(request, invoice_id: int):
    app_settings = AppSettings.get_solo()
    invoice = get_object_or_404(SalesInvoice.objects.select_related("cashier"), id=invoice_id)
    buffer = BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=A4)
    y = 810

    pdf.setFont("Helvetica-Bold", 16)
    pdf.drawString(40, y, f"{app_settings.business_name} - Sales Invoice")
    y -= 24
    pdf.setFont("Helvetica", 10)
    pdf.drawString(40, y, f"Invoice No: INV-{invoice.id}")
    pdf.drawRightString(560, y, f"Date: {timezone.localtime(invoice.timestamp).strftime('%Y-%m-%d %H:%M')}")
    y -= 16
    pdf.drawString(40, y, f"Customer: {invoice.customer_name}")
    pdf.drawRightString(560, y, f"Cashier: {invoice.cashier.username}")
    y -= 16
    pdf.drawString(40, y, f"Payment: {invoice.get_payment_method_display()} | Status: {invoice.get_status_display()}")
    pdf.drawRightString(560, y, f"Due Date: {invoice.due_date}")
    y -= 22

    pdf.setFont("Helvetica-Bold", 10)
    pdf.drawString(40, y, "Item")
    pdf.drawString(300, y, "Qty")
    pdf.drawString(360, y, "Unit Price")
    pdf.drawRightString(560, y, "Subtotal")
    y -= 8
    pdf.line(40, y, 560, y)
    y -= 14

    pdf.setFont("Helvetica", 10)
    subtotal_amount = Decimal("0.00")
    for line in invoice.line_items.select_related("product"):
        if y < 110:
            pdf.showPage()
            y = 810
            pdf.setFont("Helvetica", 10)
        pdf.drawString(40, y, f"{line.product.name}")
        pdf.drawString(300, y, str(line.quantity))
        pdf.drawString(360, y, f"{app_settings.currency_code} {line.unit_price}")
        pdf.drawRightString(560, y, f"{app_settings.currency_code} {line.subtotal}")
        subtotal_amount += line.subtotal
        y -= 16

    y -= 10
    pdf.line(340, y, 560, y)
    y -= 16
    pdf.setFont("Helvetica", 10)
    pdf.drawString(360, y, "Subtotal:")
    pdf.drawRightString(560, y, f"{app_settings.currency_code} {subtotal_amount}")
    y -= 14
    pdf.drawString(360, y, f"VAT ({app_settings.vat_rate}%):")
    pdf.drawRightString(560, y, f"{app_settings.currency_code} {invoice.tax_amount}")
    y -= 16
    pdf.setFont("Helvetica-Bold", 11)
    pdf.drawString(360, y, "Total:")
    pdf.drawRightString(560, y, f"{app_settings.currency_code} {invoice.total_amount}")
    y -= 22
    total_paid = sum((entry.amount for entry in invoice.payment_entries.all()), Decimal("0.00"))
    balance_due = invoice.total_amount - total_paid
    pdf.setFont("Helvetica", 10)
    pdf.drawString(360, y, "Paid:")
    pdf.drawRightString(560, y, f"{app_settings.currency_code} {total_paid}")
    y -= 14
    pdf.drawString(360, y, "Balance:")
    pdf.drawRightString(560, y, f"{app_settings.currency_code} {balance_due}")
    y -= 16
    pdf.drawString(40, y, f"Amount in Words: {app_settings.currency_code} {_num_to_words(int(invoice.total_amount))} only.")
    y -= 14
    pdf.drawString(40, y, f"Terms: {app_settings.invoice_terms}")
    y -= 14
    pdf.setFont("Helvetica", 9)
    pdf.drawString(40, y, app_settings.receipt_footer)

    pdf.showPage()
    pdf.save()
    buffer.seek(0)
    return FileResponse(buffer, as_attachment=True, filename=f"INV-{invoice.id}.pdf")


@login_required
@role_required("ADMIN", "MANAGER", "AUDITOR")
def sales_report(request):
    invoices = SalesInvoice.objects.all()
    now = timezone.now()
    daily = invoices.filter(timestamp__date=now.date()).aggregate(total=models.Sum("total_amount"))["total"] or Decimal("0.00")
    weekly = invoices.filter(timestamp__gte=now - timedelta(days=7)).aggregate(total=models.Sum("total_amount"))["total"] or Decimal("0.00")
    monthly = invoices.filter(timestamp__year=now.year, timestamp__month=now.month).aggregate(total=models.Sum("total_amount"))["total"] or Decimal("0.00")
    payment_breakdown = invoices.values("payment_method").annotate(
        total=models.Sum("total_amount"),
        count=models.Count("id"),
    ).order_by("payment_method")
    recent_mpesa_entries = MpesaTransaction.objects.select_related("invoice").order_by("-id")[:15]
    recent = invoices[:20]
    return render(
        request,
        "sales/report.html",
        {
            "daily_total": daily,
            "weekly_total": weekly,
            "monthly_total": monthly,
            "recent_invoices": recent,
            "payment_breakdown": payment_breakdown,
            "recent_mpesa_entries": recent_mpesa_entries,
        },
    )

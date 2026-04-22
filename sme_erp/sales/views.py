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
from inventory.services import consume_fifo_stock
from .forms import QuickSaleForm
from .models import MpesaTransaction, SalesInvoice, SalesLineItem
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


@login_required
@role_required("ADMIN", "MANAGER", "CASHIER")
def quick_sale(request):
    form = QuickSaleForm(request.POST or None)
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
                    invoice = SalesInvoice.objects.create(
                        cashier=request.user,
                        customer_name=customer_name,
                        payment_method=payment_method,
                        status=SalesInvoice.Status.PENDING_PAYMENT,
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
            return redirect("sales-receipt", invoice_id=invoice.id)
        else:
            try:
                with transaction.atomic():
                    invoice = SalesInvoice.objects.create(
                        cashier=request.user,
                        customer_name=customer_name,
                        payment_method=payment_method,
                        status=SalesInvoice.Status.PAID,
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
        return redirect("sales-receipt", invoice_id=invoice.id)
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
    return render(request, "sales/receipt.html", {"invoice": invoice})


@login_required
@role_required("ADMIN", "MANAGER", "CASHIER", "AUDITOR")
def receipt_pdf(request, invoice_id: int):
    invoice = get_object_or_404(SalesInvoice.objects.select_related("cashier"), id=invoice_id)
    buffer = BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=A4)
    y = 800
    pdf.setFont("Helvetica-Bold", 14)
    pdf.drawString(50, y, "SME ERP Receipt")
    y -= 30
    pdf.setFont("Helvetica", 11)
    pdf.drawString(50, y, f"Invoice: INV-{invoice.id}")
    y -= 20
    pdf.drawString(50, y, f"Date: {timezone.localtime(invoice.timestamp).strftime('%Y-%m-%d %H:%M')}")
    y -= 20
    pdf.drawString(50, y, f"Cashier: {invoice.cashier.username}")
    y -= 20
    pdf.drawString(50, y, f"Customer: {invoice.customer_name}")
    y -= 30
    pdf.drawString(50, y, "Items")
    y -= 20
    for line in invoice.line_items.select_related("product"):
        pdf.drawString(60, y, f"{line.product.name} x{line.quantity} @ {line.unit_price} = {line.subtotal}")
        y -= 18
    y -= 10
    pdf.drawString(50, y, f"VAT: {invoice.tax_amount}")
    y -= 20
    pdf.drawString(50, y, f"Total: {invoice.total_amount}")
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
    recent = invoices[:20]
    return render(
        request,
        "sales/report.html",
        {"daily_total": daily, "weekly_total": weekly, "monthly_total": monthly, "recent_invoices": recent},
    )

import json
import re
from datetime import timedelta
from decimal import Decimal
from io import BytesIO
from pathlib import Path

import requests
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import models, transaction
from django.http import FileResponse, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from django.conf import settings as django_settings
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

from accounts.permissions import role_required
from dashboard.models import AppSettings
from inventory.models import Product
from inventory.services import consume_fifo_stock
from .forms import CustomerForm, PaymentEntryForm, QuickSaleForm
from .models import Customer, MpesaTransaction, PaymentEntry, SalesInvoice, SalesLineItem
from .mpesa import MpesaAPIError, MpesaConfigError, initiate_stk_push


def _mark_invoice_failed(invoice_id: int | None) -> None:
    if invoice_id is None:
        return
    SalesInvoice.objects.filter(pk=invoice_id).update(status=SalesInvoice.Status.FAILED)


def _reconcile_invoice_status_from_mpesa(invoice: SalesInvoice) -> SalesInvoice:
    """
    Keep invoice status aligned with completed M-Pesa callbacks.

    In rare edge cases (callback timing or transient errors), an invoice may stay
    pending even though at least one linked M-Pesa transaction completed.
    """
    if invoice.payment_method != SalesInvoice.PaymentMethod.MPESA:
        return invoice
    has_completed_tx = invoice.mpesa_transactions.filter(status=MpesaTransaction.Status.COMPLETED).exists()
    if has_completed_tx and invoice.status != SalesInvoice.Status.PAID:
        SalesInvoice.objects.filter(pk=invoice.pk).update(status=SalesInvoice.Status.PAID)
        invoice.status = SalesInvoice.Status.PAID
    return invoice


def _coerce_mpesa_metadata_phone(value) -> str:
    if value is None:
        return ""
    s = str(value).strip()
    if re.fullmatch(r"\d+\.0", s):
        s = s[:-2]
    return s


def _sync_customer_mobile_from_mpesa(*, invoice: SalesInvoice, phone: str) -> None:
    phone = (phone or "").strip()
    if not phone:
        return
    try:
        from .mpesa import normalize_msisdn_for_daraja

        phone = normalize_msisdn_for_daraja(phone)
    except ValueError:
        pass
    cust = invoice.customer
    if not cust:
        return
    if cust.mobile != phone:
        cust.mobile = phone
        cust.save(update_fields=["mobile"])


def _resolve_customer(*, name: str, phone: str, address: str, region: str) -> Customer:
    """Resolve customer with lower collision risk than name-only matching."""
    customer = None
    if phone:
        customer = Customer.objects.filter(mobile=phone).order_by("id").first()
    if customer is None and (address or region):
        customer = Customer.objects.filter(
            name__iexact=name,
            address__iexact=address,
            region__iexact=region,
        ).order_by("id").first()
    if customer is None:
        customer = Customer.objects.filter(name__iexact=name).order_by("id").first()
    if customer is None:
        return Customer.objects.create(
            name=name,
            mobile=phone or "",
            address=address,
            region=region,
        )

    updates = {}
    if phone and customer.mobile != phone:
        updates["mobile"] = phone
    if address and customer.address != address:
        updates["address"] = address
    if region and customer.region != region:
        updates["region"] = region
    if updates:
        Customer.objects.filter(pk=customer.pk).update(**updates)
        for key, value in updates.items():
            setattr(customer, key, value)
    return customer


def _pos_page_context(form: QuickSaleForm, app_settings: AppSettings) -> dict:
    product_prices = {str(p.id): float(p.selling_price) for p in Product.objects.all()}
    return {
        "form": form,
        "pos_product_prices_json": json.dumps(product_prices),
        "pos_vat_rate": float(app_settings.vat_rate),
        "pos_currency": app_settings.currency_code,
    }


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
        customer_name = form.cleaned_data["customer_name"].strip()
        customer_address = form.cleaned_data["customer_address"].strip()
        customer_region = form.cleaned_data["customer_region"].strip()
        phone_number = (form.cleaned_data.get("phone_number") or "").strip()
        discount_kes = form.cleaned_data.get("discount_kes") or Decimal("0")
        discount_pct = form.cleaned_data.get("discount_percent") or Decimal("0")

        if quantity > product.quantity:
            messages.error(request, "Insufficient stock quantity.")
            return redirect("sales-pos")

        customer_obj = _resolve_customer(
            name=customer_name,
            phone=phone_number,
            address=customer_address,
            region=customer_region,
        )

        disc_snap = discount_pct if discount_pct > 0 else None

        if payment_method == SalesInvoice.PaymentMethod.MPESA:
            invoice = None
            try:
                with transaction.atomic():
                    invoice = SalesInvoice.objects.create(
                        cashier=request.user,
                        customer=customer_obj,
                        customer_name=customer_name,
                        payment_method=payment_method,
                        status=SalesInvoice.Status.PENDING_PAYMENT,
                        due_date=timezone.localdate() + timedelta(days=5),
                        discount_amount=discount_kes,
                        discount_percent=disc_snap,
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
                    transaction_desc="Macike sale",
                )
                with transaction.atomic():
                    MpesaTransaction.objects.create(
                        invoice=invoice,
                        checkout_request_id=stk_response.get("CheckoutRequestID"),
                        merchant_request_id=stk_response.get("MerchantRequestID"),
                        phone_number=phone_number,
                        amount=invoice.total_amount,
                        status=MpesaTransaction.Status.PENDING,
                        result_desc=stk_response.get("CustomerMessage", "STK initiated"),
                        raw_callback=stk_response,
                    )
            except MpesaConfigError as exc:
                _mark_invoice_failed(invoice.id if invoice else None)
                messages.error(request, str(exc))
                return redirect("sales-pos")
            except MpesaAPIError as exc:
                _mark_invoice_failed(invoice.id if invoice else None)
                messages.error(request, str(exc))
                return redirect("sales-pos")
            except requests.RequestException as exc:
                _mark_invoice_failed(invoice.id if invoice else None)
                messages.error(request, f"M-Pesa request failed (network): {exc}")
                return redirect("sales-pos")
            except Exception as exc:
                _mark_invoice_failed(invoice.id if invoice else None)
                messages.error(request, f"Unable to initiate STK push: {exc}")
                return redirect("sales-pos")

            messages.success(
                request,
                f"STK push sent to {phone_number}. Approve on the handset; this page updates when Daraja calls back.",
            )
            request.session["mpesa_watch_invoice_id"] = invoice.id
            # For M-Pesa, do not open receipt immediately; payment is asynchronous.
            return redirect("sales-pos")
        else:
            try:
                with transaction.atomic():
                    invoice = SalesInvoice.objects.create(
                        cashier=request.user,
                        customer=customer_obj,
                        customer_name=customer_name,
                        payment_method=payment_method,
                        status=SalesInvoice.Status.PAID,
                        due_date=timezone.localdate(),
                        discount_amount=discount_kes,
                        discount_percent=disc_snap,
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

    if request.method == "POST" and not form.is_valid():
        messages.error(request, "Checkout could not proceed. Please correct the highlighted fields and try again.")

    return render(request, "sales/pos.html", _pos_page_context(form, app_settings))


@login_required
@role_required("ADMIN", "MANAGER", "CASHIER")
def mpesa_status(request):
    invoice_id = request.session.get("mpesa_watch_invoice_id")
    if not invoice_id:
        return JsonResponse({"watching": False})

    invoice = (
        SalesInvoice.objects.filter(id=invoice_id, cashier=request.user)
        .prefetch_related("mpesa_transactions")
        .first()
    )
    if invoice is None:
        request.session.pop("mpesa_watch_invoice_id", None)
        return JsonResponse({"watching": False})

    tx = invoice.mpesa_transactions.order_by("-id").first()
    tx_status = tx.status if tx else ""
    tx_desc = tx.result_desc if tx else ""

    invoice = _reconcile_invoice_status_from_mpesa(invoice)
    is_terminal = invoice.status in {SalesInvoice.Status.PAID, SalesInvoice.Status.FAILED}
    if is_terminal:
        request.session.pop("mpesa_watch_invoice_id", None)

    return JsonResponse(
        {
            "watching": True,
            "invoice_id": invoice.id,
            "invoice_status": invoice.status,
            "transaction_status": tx_status,
            "result_desc": tx_desc,
            "is_terminal": is_terminal,
        }
    )


@csrf_exempt
@require_POST
def mpesa_callback(request):
    try:
        payload = json.loads(request.body.decode("utf-8") or "{}")
    except json.JSONDecodeError:
        return HttpResponse("Invalid JSON", status=400)

    stk = payload.get("Body", {}).get("stkCallback", {})
    checkout_request_id = stk.get("CheckoutRequestID")
    result_code = stk.get("ResultCode")
    result_desc = stk.get("ResultDesc", "")

    if not checkout_request_id:
        return HttpResponse("Missing CheckoutRequestID", status=400)

    try:
        payment_ok = int(result_code) == 0
    except (TypeError, ValueError):
        payment_ok = False

    try:
        with transaction.atomic():
            mpesa_txn = MpesaTransaction.objects.select_for_update().select_related("invoice").get(checkout_request_id=checkout_request_id)
            invoice = mpesa_txn.invoice
            if mpesa_txn.status == MpesaTransaction.Status.COMPLETED:
                return HttpResponse("OK", status=200)

            mpesa_txn.result_desc = result_desc
            mpesa_txn.raw_callback = payload

            if payment_ok:
                items = stk.get("CallbackMetadata", {}).get("Item", [])
                item_map = {item.get("Name"): item.get("Value") for item in items}
                cb_phone = _coerce_mpesa_metadata_phone(item_map.get("PhoneNumber"))
                if cb_phone:
                    mpesa_txn.phone_number = cb_phone[:20]
                mpesa_txn.mpesa_code = item_map.get("MpesaReceiptNumber", mpesa_txn.mpesa_code)
                mpesa_txn.status = MpesaTransaction.Status.COMPLETED
                _save_fields = ["mpesa_code", "status", "result_desc", "raw_callback"]
                if cb_phone:
                    _save_fields.append("phone_number")
                mpesa_txn.save(update_fields=_save_fields)
                _sync_customer_mobile_from_mpesa(invoice=invoice, phone=cb_phone or mpesa_txn.phone_number)

                if invoice.status == SalesInvoice.Status.PENDING_PAYMENT:
                    _finalize_invoice_stock(invoice)
                    invoice.status = SalesInvoice.Status.PAID
                    invoice.save(update_fields=["status"])
            else:
                mpesa_txn.status = MpesaTransaction.Status.FAILED
                mpesa_txn.save(update_fields=["status", "result_desc", "raw_callback"])
                if invoice.status == SalesInvoice.Status.PENDING_PAYMENT:
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
    invoice = get_object_or_404(
        SalesInvoice.objects.select_related("cashier", "customer"),
        id=invoice_id,
    )
    invoice = _reconcile_invoice_status_from_mpesa(invoice)
    subtotal_amount = sum((line.subtotal for line in invoice.line_items.all()), Decimal("0.00"))
    disc = Decimal(str(invoice.discount_amount or 0)).quantize(Decimal("0.01"))
    taxable_after_discount = (subtotal_amount - disc).quantize(Decimal("0.01"))
    mpesa_entries = invoice.mpesa_transactions.all().order_by("-id")
    payment_entries = invoice.payment_entries.select_related("created_by").order_by("-created_at")
    posted_entries = payment_entries.filter(status=PaymentEntry.Status.POSTED)
    total_paid = sum((entry.amount for entry in posted_entries), Decimal("0.00"))
    amount_words = _num_to_words(int(invoice.total_amount))
    if invoice.payment_method == SalesInvoice.PaymentMethod.MPESA:
        mpesa_completed = mpesa_entries.filter(status=MpesaTransaction.Status.COMPLETED).exists()
        mpesa_pending = mpesa_entries.filter(status=MpesaTransaction.Status.PENDING).exists()
        if mpesa_completed:
            total_paid = invoice.total_amount
        elif mpesa_pending:
            total_paid = Decimal("0.00")
    balance_due = invoice.total_amount - total_paid
    can_add_payment_entry = balance_due > 0 and invoice.status != SalesInvoice.Status.PAID
    customer_phone_display = ""
    if invoice.customer_id and invoice.customer.mobile:
        customer_phone_display = invoice.customer.mobile
    else:
        for tx in mpesa_entries:
            if tx.phone_number:
                customer_phone_display = tx.phone_number
                break
    return render(
        request,
        "sales/receipt.html",
        {
            "invoice": invoice,
            "subtotal_amount": subtotal_amount,
            "taxable_after_discount": taxable_after_discount,
            "mpesa_entries": mpesa_entries,
            "payment_entries": payment_entries,
            "total_paid": total_paid,
            "balance_due": balance_due,
            "can_add_payment_entry": can_add_payment_entry,
            "amount_words": amount_words,
            "customer_phone_display": customer_phone_display,
        },
    )


@login_required
@role_required("ADMIN", "MANAGER", "CASHIER")
def add_payment_entry(request, invoice_id: int):
    invoice = get_object_or_404(
        SalesInvoice.objects.prefetch_related("payment_entries"),
        id=invoice_id,
    )
    total_paid = sum(
        (e.amount for e in invoice.payment_entries.filter(status=PaymentEntry.Status.POSTED)),
        Decimal("0"),
    )
    balance_due = (invoice.total_amount - total_paid).quantize(Decimal("0.01"))
    form = PaymentEntryForm(request.POST or None, invoice=invoice)
    if request.method == "POST" and form.is_valid():
        entry = form.save(commit=False)
        entry.invoice = invoice
        entry.created_by = request.user
        entry.save()
        messages.success(request, "Payment entry added.")
        return redirect("sales-receipt", invoice_id=invoice.id)
    return render(
        request,
        "sales/payment_entry_form.html",
        {
            "invoice": invoice,
            "form": form,
            "invoice_total_paid": total_paid,
            "invoice_balance_due": balance_due,
        },
    )


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


def _pdf_logo_bytes(logo_url: str) -> bytes | None:
    if not (logo_url or "").strip():
        return None
    lu = logo_url.strip()
    try:
        if lu.startswith("http://") or lu.startswith("https://"):
            return requests.get(lu, timeout=12).content
        rel = lu.lstrip("/")
        if rel.startswith("static/"):
            rel = rel[7:]
        for static_dir in getattr(django_settings, "STATICFILES_DIRS", []):
            path = Path(static_dir) / rel
            if path.is_file():
                return path.read_bytes()
        path = Path(django_settings.BASE_DIR) / "static" / rel
        if path.is_file():
            return path.read_bytes()
    except OSError:
        return None
    except requests.RequestException:
        return None
    return None


def _pdf_draw_invoice_header(pdf: canvas.Canvas, app_settings: AppSettings, invoice, cust_phone: str, x0: float, x1: float, page_w: float) -> float:
    """Draw header band; returns y position below header (PDF coords, bottom-left origin)."""
    y_top = 800
    header_h = 88
    y_band_bottom = y_top - header_h
    pdf.setFillColor(colors.HexColor("#f0f4f8"))
    pdf.rect(x0, y_band_bottom, x1 - x0, header_h, stroke=0, fill=1)
    pdf.setFillColor(colors.HexColor("#0f4c81"))
    pdf.setStrokeColor(colors.HexColor("#0f4c81"))
    pdf.setLineWidth(3)
    pdf.line(x0, y_band_bottom, x1, y_band_bottom)

    logo_x = x0 + 8
    logo_y = y_band_bottom + 10
    logo_drawn = False
    raw = _pdf_logo_bytes(app_settings.logo_url)
    if raw:
        try:
            img = ImageReader(BytesIO(raw))
            lw, lh = 100, 52
            pdf.drawImage(img, logo_x, logo_y, width=lw, height=lh, preserveAspectRatio=True, mask="auto")
            logo_drawn = True
        except Exception:
            logo_drawn = False

    text_left = logo_x + (110 if logo_drawn else 0)
    pdf.setFillColor(colors.HexColor("#0f172a"))
    pdf.setFont("Helvetica-Bold", 20)
    pdf.drawString(text_left, y_band_bottom + 58, app_settings.business_name)
    pdf.setFont("Helvetica-Bold", 11)
    pdf.setFillColor(colors.HexColor("#334155"))
    pdf.drawString(text_left, y_band_bottom + 40, "TAX INVOICE / SALES RECEIPT")

    pdf.setFont("Helvetica", 9)
    addr_parts = [p for p in [app_settings.business_address, app_settings.business_phone, app_settings.business_email] if p]
    if addr_parts:
        pdf.drawString(text_left, y_band_bottom + 24, "  |  ".join(addr_parts[:3]))

    right_x = x1 - 8
    pdf.setFont("Helvetica-Bold", 10)
    pdf.setFillColor(colors.HexColor("#0f172a"))
    pdf.drawRightString(right_x, y_band_bottom + 58, f"Invoice No. INV-{invoice.id}")
    pdf.setFont("Helvetica", 9)
    pdf.setFillColor(colors.HexColor("#475569"))
    pdf.drawRightString(
        right_x,
        y_band_bottom + 44,
        f"Date: {timezone.localtime(invoice.timestamp).strftime('%d %b %Y %H:%M')}",
    )
    pdf.drawRightString(right_x, y_band_bottom + 32, f"Due: {invoice.due_date}")
    pdf.drawRightString(right_x, y_band_bottom + 20, f"Status: {invoice.get_status_display()}")

    y = y_band_bottom - 18
    pdf.setFont("Helvetica-Bold", 10)
    pdf.setFillColor(colors.HexColor("#0f172a"))
    pdf.drawString(x0, y, "Bill to")
    y -= 14
    pdf.setFont("Helvetica", 10)
    pdf.drawString(x0, y, invoice.customer_name)
    if cust_phone:
        y -= 13
        pdf.setFont("Helvetica", 9)
        pdf.setFillColor(colors.HexColor("#475569"))
        pdf.drawString(x0, y, f"Phone: {cust_phone}")
    y -= 8
    pdf.setFont("Helvetica", 9)
    pdf.setFillColor(colors.HexColor("#475569"))
    pdf.drawString(x0, y, f"Cashier: {invoice.cashier.username}  |  Payment: {invoice.get_payment_method_display()}")
    return y - 20


def _pdf_draw_footer(pdf: canvas.Canvas, app_settings: AppSettings, x0: float, x1: float, page_w: float, page_num: int) -> None:
    footer_top = 68
    pdf.setStrokeColor(colors.HexColor("#cbd5e1"))
    pdf.setLineWidth(0.8)
    pdf.line(x0, footer_top, x1, footer_top)
    pdf.setFont("Helvetica-Bold", 8)
    pdf.setFillColor(colors.HexColor("#0f4c81"))
    pdf.drawCentredString(page_w / 2, 54, app_settings.business_name.upper())
    pdf.setFont("Helvetica", 8)
    pdf.setFillColor(colors.HexColor("#64748b"))
    line1 = "  |  ".join(
        p for p in [app_settings.business_address, app_settings.business_phone, app_settings.business_email] if p
    )
    if line1:
        pdf.drawCentredString(page_w / 2, 42, line1[:120])
    pdf.setFont("Helvetica-Oblique", 8)
    pdf.setFillColor(colors.HexColor("#94a3b8"))
    pdf.drawCentredString(page_w / 2, 30, app_settings.receipt_footer[:140])
    pdf.setFont("Helvetica", 7)
    pdf.setFillColor(colors.HexColor("#94a3b8"))
    pdf.drawRightString(x1, 14, f"Page {page_num}")
    pdf.setFillColor(colors.black)


@login_required
@role_required("ADMIN", "MANAGER", "CASHIER", "AUDITOR")
def receipt_pdf(request, invoice_id: int):
    app_settings = AppSettings.get_solo()
    invoice = get_object_or_404(
        SalesInvoice.objects.select_related("cashier", "customer").prefetch_related("mpesa_transactions"),
        id=invoice_id,
    )
    invoice = _reconcile_invoice_status_from_mpesa(invoice)
    cust_phone = ""
    if invoice.customer_id and invoice.customer.mobile:
        cust_phone = invoice.customer.mobile
    else:
        tx = invoice.mpesa_transactions.order_by("-id").first()
        if tx and tx.phone_number:
            cust_phone = tx.phone_number

    page_w, page_h = A4
    margin = 28
    x0, x1 = margin, page_w - margin
    col_qty = x0 + 360
    col_unit = x0 + 410
    col_sub = x1

    buffer = BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=A4)
    page_num = 1

    y = _pdf_draw_invoice_header(pdf, app_settings, invoice, cust_phone, x0, x1, page_w)

    pdf.setStrokeColor(colors.HexColor("#0f4c81"))
    pdf.setLineWidth(1)
    pdf.line(x0, y + 8, x1, y + 8)
    y -= 6

    subtotal_amount = Decimal("0.00")
    footer_reserve = 118
    line_h = 15

    def _pdf_table_column_titles(cy: float) -> float:
        c = pdf
        c.setFont("Helvetica-Bold", 9)
        c.setFillColor(colors.HexColor("#0f172a"))
        c.drawString(x0, cy, "Description")
        c.drawString(col_qty, cy, "Qty")
        c.drawString(col_unit, cy, "Unit price")
        c.drawRightString(col_sub, cy, "Amount")
        cy -= 6
        c.setStrokeColor(colors.HexColor("#e2e8f0"))
        c.line(x0, cy, x1, cy)
        cy -= 14
        c.setFont("Helvetica", 9)
        c.setFillColor(colors.HexColor("#1e293b"))
        return cy

    def _pdf_new_page():
        nonlocal y, page_num
        _pdf_draw_footer(pdf, app_settings, x0, x1, page_w, page_num)
        pdf.showPage()
        page_num += 1
        y = _pdf_draw_invoice_header(pdf, app_settings, invoice, cust_phone, x0, x1, page_w)
        y -= 12
        return _pdf_table_column_titles(y)

    y = _pdf_table_column_titles(y)

    for line in invoice.line_items.select_related("product", "product__supplier"):
        if y < footer_reserve + line_h:
            y = _pdf_new_page()
        name = (line.product.name or "")[:85]
        pdf.drawString(x0, y, name)
        pdf.drawString(col_qty, y, str(line.quantity))
        pdf.drawString(col_unit, y, f"{app_settings.currency_code} {line.unit_price}")
        pdf.drawRightString(col_sub, y, f"{app_settings.currency_code} {line.subtotal}")
        subtotal_amount += line.subtotal
        y -= line_h

    totals_block_h = 120
    if y < footer_reserve + totals_block_h:
        y = _pdf_new_page()

    y -= 8
    pdf.setStrokeColor(colors.HexColor("#cbd5e1"))
    pdf.line(x0 + 260, y + 10, x1, y + 10)
    y -= 6

    total_paid = sum(
        (entry.amount for entry in invoice.payment_entries.filter(status=PaymentEntry.Status.POSTED)),
        Decimal("0.00"),
    )
    balance_due = invoice.total_amount - total_paid

    pdf.setFont("Helvetica", 9)
    pdf.drawRightString(col_sub - 120, y, "Subtotal (gross)")
    pdf.drawRightString(col_sub, y, f"{app_settings.currency_code} {subtotal_amount}")
    y -= line_h
    disc_amt = Decimal(str(invoice.discount_amount or 0)).quantize(Decimal("0.01"))
    if disc_amt > 0:
        pdf.setFillColor(colors.HexColor("#b91c1c"))
        pdf.drawRightString(col_sub - 120, y, "Discount")
        pdf.drawRightString(col_sub, y, f"- {app_settings.currency_code} {disc_amt}")
        y -= line_h
        pdf.setFillColor(colors.HexColor("#1e293b"))
        taxable_pdf = (subtotal_amount - disc_amt).quantize(Decimal("0.01"))
        pdf.drawRightString(col_sub - 120, y, "After discount")
        pdf.drawRightString(col_sub, y, f"{app_settings.currency_code} {taxable_pdf}")
        y -= line_h
    pdf.drawRightString(col_sub - 120, y, f"VAT ({app_settings.vat_rate}%)")
    pdf.drawRightString(col_sub, y, f"{app_settings.currency_code} {invoice.tax_amount}")
    y -= line_h
    pdf.setFont("Helvetica-Bold", 11)
    pdf.setFillColor(colors.HexColor("#0f4c81"))
    pdf.drawRightString(col_sub - 120, y, "Total due")
    pdf.drawRightString(col_sub, y, f"{app_settings.currency_code} {invoice.total_amount}")
    y -= line_h + 4
    pdf.setFont("Helvetica", 9)
    pdf.setFillColor(colors.HexColor("#1e293b"))
    pdf.drawRightString(col_sub - 120, y, "Paid")
    pdf.drawRightString(col_sub, y, f"{app_settings.currency_code} {total_paid}")
    y -= line_h
    pdf.drawRightString(col_sub - 120, y, "Balance")
    pdf.drawRightString(col_sub, y, f"{app_settings.currency_code} {balance_due}")
    y -= 20

    if y < footer_reserve + 36:
        y = _pdf_new_page()

    pdf.setFont("Helvetica", 8)
    pdf.setFillColor(colors.HexColor("#475569"))
    words = _num_to_words(int(invoice.total_amount))
    pdf.drawString(x0, y, f"Amount in words: {app_settings.currency_code} {words} only.")
    y -= 12
    pdf.drawString(x0, y, f"Terms & conditions: {app_settings.invoice_terms}")

    _pdf_draw_footer(pdf, app_settings, x0, x1, page_w, page_num)
    pdf.save()
    buffer.seek(0)
    return FileResponse(buffer, as_attachment=True, filename=f"INV-{invoice.id}.pdf")


@login_required
@role_required("ADMIN", "MANAGER", "AUDITOR")
def sales_report(request):
    invoices = SalesInvoice.objects.all()
    paid_invoices = invoices.filter(status=SalesInvoice.Status.PAID)
    now = timezone.now()

    def money2(value) -> Decimal:
        return Decimal(str(value or 0)).quantize(Decimal("0.01"))

    daily = money2(
        paid_invoices.filter(timestamp__date=now.date()).aggregate(total=models.Sum("total_amount"))["total"],
    )
    weekly = money2(
        paid_invoices.filter(timestamp__gte=now - timedelta(days=7)).aggregate(total=models.Sum("total_amount"))["total"],
    )
    monthly = money2(
        paid_invoices.filter(timestamp__year=now.year, timestamp__month=now.month).aggregate(total=models.Sum("total_amount"))[
            "total"
        ],
    )
    payment_rows = paid_invoices.values("payment_method").annotate(
        total=models.Sum("total_amount"),
        count=models.Count("id"),
    ).order_by("payment_method")
    pm_labels = dict(SalesInvoice.PaymentMethod.choices)
    payment_breakdown = [
        {
            "label": pm_labels.get(row["payment_method"], row["payment_method"]),
            "count": row["count"],
            "total": money2(row["total"]),
        }
        for row in payment_rows
    ]
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

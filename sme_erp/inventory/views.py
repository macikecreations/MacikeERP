from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db import models, transaction
from django.shortcuts import redirect, render

from accounts.permissions import role_required
from .forms import ProductCategoryForm, ProductForm, RestockForm, SupplierForm
from .models import Product, ProductCategory, StockAuditLog, StockBatch, Supplier
from .services import restock


@login_required
def product_list(request):
    products_qs = Product.objects.select_related("category").all().order_by("name")
    q = request.GET.get("q", "").strip()
    status = request.GET.get("status", "").strip()
    if q:
        products_qs = products_qs.filter(models.Q(name__icontains=q) | models.Q(sku__icontains=q))
    if status == "low":
        products_qs = products_qs.filter(quantity__lte=models.F("reorder_level"))
    elif status == "ok":
        products_qs = products_qs.filter(quantity__gt=models.F("reorder_level"))

    paginator = Paginator(products_qs, 8)
    page_obj = paginator.get_page(request.GET.get("page"))
    return render(
        request,
        "inventory/product_list.html",
        {"products": page_obj.object_list, "page_obj": page_obj, "q": q, "status": status},
    )


@login_required
@role_required("ADMIN", "MANAGER")
def product_create(request):
    form = ProductForm(request.POST or None)
    if ProductCategory.objects.count() == 0:
        messages.warning(request, "Create at least one category first.")
        return redirect("inventory-category-create")

    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            product = form.save()
            # If opening stock is set during product creation, seed FIFO with one batch.
            if product.quantity > 0:
                StockBatch.objects.create(
                    product=product,
                    quantity_received=product.quantity,
                    quantity_remaining=product.quantity,
                    unit_cost=product.cost_price,
                )
                StockAuditLog.objects.create(
                    product=product,
                    user=request.user,
                    action_type=StockAuditLog.ActionType.RESTOCK,
                    quantity_changed=product.quantity,
                    remarks="Opening stock at product creation",
                )
        messages.success(request, f"Product '{product.name}' created successfully.")
        return redirect("inventory-list")
    if request.method == "POST":
        error_count = sum(len(errs) for errs in form.errors.values())
        messages.error(request, f"Please fix the form errors and try again ({error_count} error(s)).")
    return render(request, "inventory/product_form.html", {"form": form})


@login_required
@role_required("ADMIN", "MANAGER")
def restock_product(request):
    form = RestockForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        restock(
            product=form.cleaned_data["product"],
            quantity=form.cleaned_data["quantity"],
            unit_cost=form.cleaned_data["unit_cost"],
            user=request.user,
            remarks=form.cleaned_data["remarks"] or "Manual restock",
        )
        messages.success(request, "Stock restocked successfully.")
        return redirect("inventory-list")
    if request.method == "POST":
        messages.error(request, "Please fix the form errors and try again.")
    return render(request, "inventory/restock_form.html", {"form": form})


@login_required
@role_required("ADMIN", "MANAGER")
def category_create(request):
    form = ProductCategoryForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Category created.")
        return redirect("inventory-list")
    return render(request, "inventory/category_form.html", {"form": form})


@login_required
@role_required("ADMIN", "MANAGER")
def supplier_create(request):
    form = SupplierForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Supplier created.")
        return redirect("inventory-list")
    return render(request, "inventory/supplier_form.html", {"form": form})

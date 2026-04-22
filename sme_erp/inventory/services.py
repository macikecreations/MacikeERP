from django.db import transaction

from .models import Product, StockAuditLog, StockBatch


@transaction.atomic
def consume_fifo_stock(*, product: Product, quantity: int, user, remarks: str = "") -> None:
    remaining = quantity
    batches = StockBatch.objects.select_for_update().filter(product=product, quantity_remaining__gt=0).order_by("received_at", "id")
    for batch in batches:
        if remaining <= 0:
            break
        take = min(batch.quantity_remaining, remaining)
        batch.quantity_remaining -= take
        batch.save(update_fields=["quantity_remaining"])
        remaining -= take
    if remaining > 0:
        raise ValueError("Not enough FIFO batch quantity.")

    product.quantity -= quantity
    product.save(update_fields=["quantity"])
    StockAuditLog.objects.create(
        product=product,
        user=user,
        action_type=StockAuditLog.ActionType.SALE,
        quantity_changed=-quantity,
        remarks=remarks,
    )


@transaction.atomic
def restock(*, product: Product, quantity: int, unit_cost, user, remarks: str = "") -> None:
    StockBatch.objects.create(
        product=product,
        quantity_received=quantity,
        quantity_remaining=quantity,
        unit_cost=unit_cost,
    )
    product.quantity += quantity
    product.cost_price = unit_cost
    product.save(update_fields=["quantity", "cost_price"])
    StockAuditLog.objects.create(
        product=product,
        user=user,
        action_type=StockAuditLog.ActionType.RESTOCK,
        quantity_changed=quantity,
        remarks=remarks,
    )

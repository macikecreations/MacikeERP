from django.urls import path

from .views import (
    category_create,
    product_create,
    product_delete,
    product_edit,
    product_list,
    restock_product,
    supplier_create,
)

urlpatterns = [
    path("", product_list, name="inventory-list"),
    path("new/", product_create, name="inventory-create"),
    path("<int:product_id>/edit/", product_edit, name="inventory-edit"),
    path("<int:product_id>/delete/", product_delete, name="inventory-delete"),
    path("restock/", restock_product, name="inventory-restock"),
    path("categories/new/", category_create, name="inventory-category-create"),
    path("suppliers/new/", supplier_create, name="inventory-supplier-create"),
]

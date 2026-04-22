from django import forms

from .models import Product, ProductCategory, Supplier


class ProductForm(forms.ModelForm):
    class Meta:
        model = Product
        fields = [
            "category",
            "supplier",
            "name",
            "sku",
            "cost_price",
            "selling_price",
            "quantity",
            "reorder_level",
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs["class"] = "form-control"
        self.fields["supplier"].required = False


class RestockForm(forms.Form):
    product = forms.ModelChoiceField(queryset=Product.objects.all())
    quantity = forms.IntegerField(min_value=1)
    unit_cost = forms.DecimalField(max_digits=10, decimal_places=2, min_value=0)
    remarks = forms.CharField(max_length=255, required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs["class"] = "form-control"


class ProductCategoryForm(forms.ModelForm):
    class Meta:
        model = ProductCategory
        fields = ["name", "description", "is_active"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name, field in self.fields.items():
            css = "form-check-input" if name == "is_active" else "form-control"
            field.widget.attrs["class"] = css


class SupplierForm(forms.ModelForm):
    class Meta:
        model = Supplier
        fields = ["company_name", "contact_person", "email", "phone", "kra_pin"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs["class"] = "form-control"

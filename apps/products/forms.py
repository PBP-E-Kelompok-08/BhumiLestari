from django import forms
from .models import Product

class ProductForm(forms.ModelForm):
    class Meta:
        model = Product
        fields = ["name", "description", "price", "stock", "image"]
        labels = {
            "name": "Nama Produk",
            "description": "Deskripsi",
            "price": "Harga (Rp)",
            "stock": "Stok",
            "image": "Foto Produk",
        }
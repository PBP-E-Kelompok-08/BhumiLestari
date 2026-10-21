from django import forms
from .models import Product
from .validators import validate_file_size, validate_file_extension, validate_file_content

class ProductForm(forms.ModelForm):
    class Meta:
        model = Product
        fields = ["name", "description", "price", "stock", "image", "certification"]
        labels = {
            "name": "Nama Produk",
            "description": "Deskripsi",
            "price": "Harga (Rp)",
            "stock": "Stok",
            "image": "Foto Produk",
            "certification": "Sertifikasi Eco-Friendly Produk",
        }

        widgets = {
            "name": forms.TextInput(
                attrs={
                    "placeholder": "Contoh: Sedotan Bambu Neo Series",
                }
            ),
            "description": forms.Textarea(
                attrs={
                    "rows": 4,
                    "placeholder": "Deskripsikan produk Anda",
                }
            ),
            "price": forms.NumberInput(
                attrs={
                    "min": 0,
                    "placeholder": "Contoh: 25000",
                }
            ),
            "stock": forms.NumberInput(
                attrs={
                    "min": 0,
                    "placeholder": "Contoh: 100",
                }
            ),
            "image": forms.FileInput(
                attrs={
                    "accept": "image/jpeg,image/jpg,image/png",
                }
            ),
            "certification": forms.FileInput(
                attrs={
                    "accept": "application/pdf,image/jpeg,image/jpg,image/png",
                }
            ),
        }

    def clean_image(self):
        image = self.cleaned_data.get("image")
        if image:
            validate_file_size(image)
        return image

    def clean_certification(self):
        cert = self.cleaned_data.get("certification")
        if cert:
            validate_file_size(cert)
            validate_file_extension(cert, ["pdf", "jpg", "jpeg", "png"])
            validate_file_content(cert)
        return cert
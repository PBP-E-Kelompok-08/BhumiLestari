from django import forms
from .models import Product
from .validators import validate_file_size, validate_file_extension, validate_file_content

class ProductForm(forms.ModelForm):
    class Meta:
        model = Product
        fields = ["name", "description", "category", "stock", "price", "discount", "image", "certification"]
        labels = {
            "name": "Nama Produk",
            "description": "Deskripsi Produk",
            "category": "Kategori",
            "stock": "Stok",
            "price": "Harga (Rp)",
            "discount": "Diskon (Opsional)",
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
                    "placeholder": "Masukkan deskripsi produk Anda",
                }
            ),
            "stock": forms.NumberInput(
                attrs={
                    "min": 0,
                    "placeholder": "0",
                }
            ),
            "price": forms.NumberInput(
                attrs={
                    "min": 0,
                    "placeholder": "Rp. 0",
                }
            ),
            "discount": forms.NumberInput(
                attrs={
                    "min": 0,
                    "max": 100,
                    "placeholder": "0 %",
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
        certificate = self.cleaned_data.get("certification")
        if certificate:
            validate_file_size(certificate)
            validate_file_extension(certificate, ["pdf", "jpg", "jpeg", "png"])
            validate_file_content(certificate)
        return certificate
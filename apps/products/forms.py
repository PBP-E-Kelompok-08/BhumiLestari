from django import forms
from .models import Product
from .validators import validate_file_size, validate_file_extension, validate_file_content

class ProductForm(forms.ModelForm):
    class Meta:
        model = Product
        fields = [
            "name", "description", "category", "eco_features", "materials",
            "origin", "price", "stock", "discount", "image",
            "verification_document",
        ]
        labels = {
            "name": "Nama Produk",
            "description": "Deskripsi Produk",
            "category": "Kategori",
            "eco_features": "Fitur Ramah Lingkungan",
            "materials": "Material Produk",
            "origin": "Asal Produk",
            "price": "Harga (Rp)",
            "stock": "Stok",
            "discount": "Diskon (Opsional)",
            "image": "Foto Produk",
            "verification_document": "Sertifikasi Eco-Friendly Produk",
        }

        widgets = {
            "name": forms.TextInput(attrs={"placeholder": "Contoh: Sedotan Bambu Neo Series"}),
            "description": forms.Textarea(attrs={"rows": 4, "placeholder": "Masukkan deskripsi produk Anda"}),
            "eco_features": forms.CheckboxSelectMultiple,
            "materials": forms.TextInput(attrs={"placeholder": "Pisahkan dengan koma, contoh: bambu, katun"}),
            "origin": forms.TextInput(attrs={"placeholder": "Contoh: Bandung, Jawa Barat"}),
            "stock": forms.NumberInput(attrs={"min": 0, "placeholder": "0"}),
            "price": forms.NumberInput(attrs={"min": 0, "placeholder": "Rp. 0"}),
            "discount": forms.NumberInput(attrs={"min": 0, "max": 100, "placeholder": "0 %"}),
            "image": forms.FileInput(attrs={"accept": "image/jpeg,image/jpg,image/png"}),
            "verification_document": forms.FileInput(attrs={"accept": "application/pdf,image/jpeg,image/jpg,image/png"}),
        }

    def clean_image(self):
        image = self.cleaned_data.get("image")
        if image:
            validate_file_size(image)
        return image

    def clean_verification_document(self):
        document = self.cleaned_data.get("verification_document")
        if document:
            validate_file_size(document)
            validate_file_extension(document, ["pdf", "jpg", "jpeg", "png"])
            validate_file_content(document)
        return document
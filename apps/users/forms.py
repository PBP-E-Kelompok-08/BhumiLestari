from django import forms
from django.core.exceptions import ValidationError
from django.core.validators import FileExtensionValidator

MAX_LOGO_SIZE = 2 * 1024 * 1024

def validasi_logo(f):
    frmt = getattr(getattr(f, "image", None), "format", None)
    if frmt not in ("JPEG", "PNG"):
        raise ValidationError("Logo harus berformat JPG atau PNG")
    if f.size > MAX_LOGO_SIZE:
        raise ValidationError("Ukuran logo maksimal 2 MB")

class LogoForm(forms.Form):
    logo = forms.ImageField(
        required=False, 
        validators=[
            FileExtensionValidator(allowed_extensions=["jpg", "jpeg", "png"]),
            validasi_logo,
            ],
        )
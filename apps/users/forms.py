from django import forms
from django.core.exceptions import ValidationError
from django.core.validators import FileExtensionValidator
from .models import PaymentMethod

MAX_LOGO_SIZE = 2 * 1024 * 1024
PROVIDERS = {
    'bank' : ['BCA', 'Mandiri', 'BNI', 'BRI'],
    'ewallet' : ['Gopay', 'Ovo', 'Dana', 'Shopeepay'] 
}
ALLOWED_TYPES = [('bank', 'Bank'), ('ewallet', 'E-Wallet')]

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

class PaymentForm(forms.ModelForm):
    method_type = forms.ChoiceField(choices=ALLOWED_TYPES)
    provider = forms.ChoiceField(
        choices=[(p, p) for daftar in PROVIDERS.values() for p in daftar]
    )

    class Meta:
        model = PaymentMethod
        fields =['method_type', 'provider', 'account_number']

    def clean_account_number(self):
        number = self.cleaned_data['account_number'].strip()
        if not number.isdigit():
            raise ValidationError('Nomor hanya boleh berisi angka.')
        if not 8 <= len(number) <= 20:
            raise ValidationError('Nomor harus 8 sampai 20 digit.')
        return number

    def clean(self):
        cleaned = super().clean()
        tipe = cleaned.get('method_type')
        provider = cleaned.get('provider')
        if tipe and provider and provider not in PROVIDERS[tipe]:
            self.add_error('provider', 'Provider tidak sesuai dengan tipe yang dipilih.')
        return cleaned



"""Form modul ulasan.

Dipakai di dua tempat:
- view JSON (validasi input POST: tambah/edit ulasan, balas, laporkan), dan
- template halaman ulasan (render field + filter), supaya aturan validasi hanya ada satu.
"""
from django import forms
from PIL import Image

MAKS_FOTO = 3
MAKS_UKURAN_FOTO = 2 * 1024 * 1024  # 2 MB
TIPE_FOTO = {"image/jpeg", "image/png", "image/webp"}
MAKS_KOMENTAR = 1000
MAKS_BALASAN = 300
MAKS_ALASAN = 300
MIN_ALASAN = 5

PILIHAN_RATING = [(5, "5 ★"), (4, "4 ★"), (3, "3 ★"), (2, "2 ★"), (1, "1 ★")]
PILIHAN_URUTAN = [
    ("terbaru", "Terbaru"),
    ("tertinggi", "Rating tertinggi"),
    ("terendah", "Rating terendah"),
]


# ---------------------------------------------------------------------------
# Upload banyak foto (pola resmi Django untuk multiple file)
# ---------------------------------------------------------------------------
class MultipleFileInput(forms.ClearableFileInput):
    allow_multiple_selected = True


class MultipleFileField(forms.FileField):
    def __init__(self, *args, **kwargs):
        kwargs.setdefault("widget", MultipleFileInput())
        super().__init__(*args, **kwargs)

    def clean(self, data, initial=None):
        satu = super().clean
        if isinstance(data, (list, tuple)):
            hasil = [satu(d, initial) for d in data]
        else:
            hasil = [satu(data, initial)]
        hasil = [f for f in hasil if f]

        if len(hasil) > MAKS_FOTO:
            raise forms.ValidationError(f"Maksimal {MAKS_FOTO} foto.")
        for f in hasil:
            if getattr(f, "content_type", None) not in TIPE_FOTO:
                raise forms.ValidationError("Format foto harus JPG, PNG, atau WEBP.")
            if f.size > MAKS_UKURAN_FOTO:
                raise forms.ValidationError("Ukuran tiap foto maksimal 2 MB.")
            # Validasi Magic Bytes & Integritas File via Pillow (mencegah file berbahaya disamarkan)
            try:
                if hasattr(f, "seek"):
                    f.seek(0)
                img = Image.open(f)
                img.verify()
                if hasattr(f, "seek"):
                    f.seek(0)
            except Exception:
                raise forms.ValidationError("Berkas yang diunggah rusak atau bukan gambar yang valid.")
        return hasil


# ---------------------------------------------------------------------------
# Ulasan (buyer)
# ---------------------------------------------------------------------------
class UlasanEditForm(forms.Form):
    """Rating + komentar. Dipakai untuk edit ulasan dan sebagai dasar form tambah."""

    rating = forms.TypedChoiceField(
        label="Rating",
        choices=PILIHAN_RATING,
        coerce=int,
        widget=forms.RadioSelect,
        error_messages={
            "required": "Rating harus berupa angka 1-5.",
            "invalid_choice": "Rating harus berupa angka 1-5.",
        },
    )
    komentar = forms.CharField(
        label="Komentar",
        required=False,
        max_length=MAKS_KOMENTAR,
        widget=forms.Textarea(
            attrs={"rows": 4, "placeholder": "Ceritakan pengalaman Anda dengan produk ini..."}
        ),
        error_messages={"max_length": f"Komentar maksimal {MAKS_KOMENTAR} karakter."},
    )


class UlasanBaruForm(UlasanEditForm):
    produk_id = forms.UUIDField(
        label="Produk",
        error_messages={
            "required": "Pilih produk yang ingin diulas.",
            "invalid": "Pilih produk yang ingin diulas.",
        },
    )
    foto = MultipleFileField(
        label=f"Foto (maks. {MAKS_FOTO}, JPG/PNG/WEBP, 2 MB)",
        required=False,
        widget=MultipleFileInput(attrs={"accept": "image/jpeg,image/png,image/webp"}),
    )

    # urutan field = urutan pesan error (rating -> komentar -> produk -> foto)
    field_order = ["rating", "komentar", "produk_id", "foto"]

    def __init__(self, *args, produk_choices=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["komentar"].widget.attrs.update({"rows": 1, "placeholder": "Tulis Ulasan..."})
        if produk_choices is not None:
            pilihan = forms.Select(choices=[("", "Pilih produk...")] + list(produk_choices))
            pilihan.is_required = True
            self.fields["produk_id"].widget = pilihan


# ---------------------------------------------------------------------------
# Balasan & laporan (seller)
# ---------------------------------------------------------------------------
class BalasanForm(forms.Form):
    pesan = forms.CharField(
        label="Balasan",
        max_length=MAKS_BALASAN,
        widget=forms.Textarea(attrs={"rows": 3, "placeholder": "Tulis balasan untuk pembeli..."}),
        error_messages={
            "required": "Kolom pesan wajib diisi.",
            "max_length": f"Maksimal {MAKS_BALASAN} karakter.",
        },
    )


class LaporanForm(forms.Form):
    alasan = forms.CharField(
        label="Alasan laporan",
        min_length=MIN_ALASAN,
        max_length=MAKS_ALASAN,
        widget=forms.Textarea(attrs={"rows": 3, "placeholder": "Mengapa ulasan ini melanggar aturan?"}),
        error_messages={
            "required": "Kolom alasan wajib diisi.",
            "min_length": f"Alasan minimal {MIN_ALASAN} karakter.",
            "max_length": f"Maksimal {MAKS_ALASAN} karakter.",
        },
    )


# ---------------------------------------------------------------------------
# Filter daftar ulasan (GET)
# ---------------------------------------------------------------------------
class FilterUlasanForm(forms.Form):
    # rating & foto dikendalikan chip "Semua / Dengan Foto / 5..1" di halaman -> input hidden
    rating = forms.ChoiceField(
        label="Rating",
        required=False,
        choices=[("", "Semua rating")] + [(str(n), t) for n, t in PILIHAN_RATING],
        widget=forms.HiddenInput,
    )
    foto = forms.CharField(label="Dengan foto", required=False, widget=forms.HiddenInput)
    produk = forms.ChoiceField(label="Produk", required=False, choices=[("", "Semua produk")])
    urut = forms.ChoiceField(label="Urutkan", required=False, choices=PILIHAN_URUTAN)
    terverifikasi = forms.BooleanField(label="Hanya produk terverifikasi", required=False)
    belum_dibalas = forms.BooleanField(label="Belum dibalas", required=False)

    def __init__(self, *args, produk_choices=(), boleh_belum_dibalas=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["produk"].choices = [("", "Semua produk")] + list(produk_choices)
        if not boleh_belum_dibalas:
            del self.fields["belum_dibalas"]

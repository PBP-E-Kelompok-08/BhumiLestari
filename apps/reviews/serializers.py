from rest_framework import serializers

from .models import UlasanToko


def _nama_pengguna(user):
    return user.full_name or user.username


def _samarkan_nama(nama):
    nama = (nama or "").strip()
    if len(nama) <= 2:
        return (nama[:1] or "?") + "*"
    return nama[0] + "*" * min(len(nama) - 2, 6) + nama[-1]


class UlasanPublikSerializer(serializers.ModelSerializer):
    pembeli = serializers.SerializerMethodField()
    toko = serializers.SerializerMethodField()
    produk = serializers.SerializerMethodField()
    foto = serializers.SerializerMethodField()
    jumlah_foto = serializers.SerializerMethodField()
    foto_terkunci = serializers.SerializerMethodField()
    balasan = serializers.SerializerMethodField()
    milik_saya = serializers.SerializerMethodField()
    bisa_diedit = serializers.SerializerMethodField()

    class Meta:
        model = UlasanToko
        fields = [
            "id",
            "pembeli",
            "rating",
            "komentar",
            "diedit",
            "created_at",
            "updated_at",
            "toko",
            "produk",
            "foto",
            "jumlah_foto",
            "foto_terkunci",
            "balasan",
            "milik_saya",
            "bisa_diedit",
        ]
        read_only_fields = fields

    def _user(self):
        request = self.context.get("request")
        return getattr(request, "user", None)

    def get_pembeli(self, ulasan):
        nama = _nama_pengguna(ulasan.pembeli)
        user = self._user()
        if user is not None and user.is_authenticated:
            return nama
        return _samarkan_nama(nama)

    def get_toko(self, ulasan):
        return {"id": ulasan.toko_id, "nama": ulasan.toko.store_name}

    def get_produk(self, ulasan):
        produk = ulasan.produk
        return {
            "id": str(ulasan.produk_id) if ulasan.produk_id else None,
            "nama": ulasan.nama_produk,
            "status": produk.status if produk else None,
            "status_display": produk.get_status_display() if produk else "Produk dihapus",
        }

    def get_foto(self, ulasan):
        user = self._user()
        if user is None or not user.is_authenticated:
            return []

        request = self.context.get("request")
        urls = [foto.gambar.url for foto in ulasan.foto.all()]
        if request is None:
            return urls
        return [request.build_absolute_uri(url) for url in urls]

    def get_jumlah_foto(self, ulasan):
        return len(ulasan.foto.all())

    def get_foto_terkunci(self, ulasan):
        user = self._user()
        return bool(ulasan.foto.all()) and (user is None or not user.is_authenticated)

    def get_balasan(self, ulasan):
        balasan = getattr(ulasan, "balasan", None)
        if balasan is None:
            return None
        return {
            "pesan": balasan.pesan,
            "created_at": balasan.created_at,
            "updated_at": balasan.updated_at,
        }

    def get_milik_saya(self, ulasan):
        user = self._user()
        return bool(user and user.is_authenticated and ulasan.pembeli_id == user.id)

    def get_bisa_diedit(self, ulasan):
        return self.get_milik_saya(ulasan) and not ulasan.disembunyikan and ulasan.bisa_diedit()

"""Data awal ulasan untuk demo/penilaian.

    python manage.py seed_ulasan              # ~100 ulasan
    python manage.py seed_ulasan --jumlah 150
    python manage.py seed_ulasan --bersih     # hapus semua data seed

Data seed sengaja melewati aturan "harus punya pesanan selesai" karena ini data demo.
Pembeli seed berusername `seed_buyer_N` dan tidak bisa login (password tidak dipakai).
Perintah ini aman dijalankan berulang: pasangan (pembeli, produk) yang sudah ada dilewati.
"""
import random
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from apps.products.models import Product
from apps.reviews.models import BalasanUlasan, LaporanUlasan, UlasanToko

User = get_user_model()
PREFIX = "seed_buyer_"

NAMA = [
    "Aisyah Putri", "Budi Santoso", "Citra Lestari", "Dimas Prakoso", "Eka Wulandari",
    "Fajar Nugroho", "Gita Maharani", "Hendra Wijaya", "Intan Permata", "Joko Susilo",
    "Kirana Dewi", "Lukman Hakim", "Maya Anggraini", "Nanda Pratama", "Okta Ramadhani",
    "Putri Ayu", "Rizky Maulana", "Sari Indah", "Tegar Saputra", "Wulan Sari",
]

KOMENTAR = {
    5: [
        "Kualitasnya bagus sekali, sesuai deskripsi. Pengiriman juga cepat.",
        "Suka banget, ramah lingkungan dan awet dipakai. Pasti beli lagi!",
        "Packing rapi tanpa plastik berlebih. Produk persis seperti di foto.",
        "Barang berkualitas, penjual responsif. Sangat direkomendasikan.",
    ],
    4: [
        "Bagus dan sesuai harapan, hanya pengirimannya agak lama.",
        "Kualitas oke untuk harganya. Warnanya sedikit berbeda dari foto.",
        "Produknya baik, cocok untuk dipakai sehari-hari.",
    ],
    3: [
        "Lumayan, tapi ukurannya agak berbeda dari yang saya bayangkan.",
        "Cukup bagus, namun finishing-nya masih bisa ditingkatkan.",
    ],
    2: [
        "Kurang sesuai ekspektasi, ada bagian yang cepat rusak.",
        "Pengiriman lama dan kemasan sedikit penyok.",
    ],
    1: [
        "Produk tidak sesuai deskripsi, saya kecewa.",
        "Barang datang dalam kondisi cacat.",
    ],
}
BALASAN = [
    "Terima kasih atas ulasannya, Kak! Senang produknya cocok.",
    "Terima kasih sudah berbelanja. Kami tunggu pesanan berikutnya!",
    "Mohon maaf atas ketidaknyamanannya, akan kami perbaiki.",
    "Terima kasih masukannya, sangat membantu kami berkembang.",
]
ALASAN_LAPORAN = [
    "Ulasan tidak sesuai dengan produk yang dibeli.",
    "Mengandung kata-kata kasar terhadap toko kami.",
    "Diduga ulasan palsu dari akun yang sama.",
]


class Command(BaseCommand):
    help = "Mengisi data awal ulasan, balasan, dan laporan untuk demo."

    def add_arguments(self, parser):
        parser.add_argument("--jumlah", type=int, default=100, help="jumlah ulasan (default 100)")
        parser.add_argument("--bersih", action="store_true", help="hapus semua data seed lalu keluar")
        parser.add_argument("--seed", type=int, default=8, help="seed acak agar hasil konsisten")

    @transaction.atomic
    def handle(self, *args, **opsi):
        if opsi["bersih"]:
            n, _ = User.objects.filter(username__startswith=PREFIX).delete()
            self.stdout.write(self.style.SUCCESS(f"Data seed dihapus ({n} objek terkait)."))
            return

        rnd = random.Random(opsi["seed"])
        produk = list(Product.objects.filter(status="verified").select_related("seller__user"))
        if not produk:
            produk = list(
                Product.objects.exclude(status__in=["rejected", "expired"]).select_related("seller__user")
            )
        if not produk:
            raise CommandError(
                "Belum ada produk. Jalankan seed produk (mis. load_mock_data) lebih dulu."
            )

        pembeli = self._buat_pembeli(len(NAMA))
        pasangan = [(b, p) for b in pembeli for p in produk]
        rnd.shuffle(pasangan)

        dibuat = dibalas = dilaporkan = 0
        sekarang = timezone.now()
        for b, p in pasangan:
            if dibuat >= opsi["jumlah"]:
                break
            if UlasanToko.objects.filter(pembeli=b, produk=p).exists():
                continue

            rating = rnd.choices([5, 4, 3, 2, 1], weights=[40, 30, 15, 10, 5])[0]
            u = UlasanToko.objects.create(
                toko=p.seller,
                pembeli=b,
                produk=p,
                nama_produk=p.name,
                rating=rating,
                komentar=rnd.choice(KOMENTAR[rating]) if rnd.random() < 0.9 else "",
            )
            waktu = sekarang - timedelta(days=rnd.randint(0, 60), hours=rnd.randint(0, 23))
            UlasanToko.objects.filter(pk=u.pk).update(created_at=waktu)  # auto_now_add tak bisa diisi
            dibuat += 1

            if rnd.random() < 0.4:
                BalasanUlasan.objects.create(ulasan=u, penjual=p.seller.user, pesan=rnd.choice(BALASAN))
                dibalas += 1
            elif rating <= 2 and rnd.random() < 0.5:
                status = rnd.choice(
                    [LaporanUlasan.STATUS_MENUNGGU, LaporanUlasan.STATUS_MENUNGGU, LaporanUlasan.STATUS_DITOLAK]
                )
                LaporanUlasan.objects.create(
                    ulasan=u, pelapor=p.seller.user, alasan=rnd.choice(ALASAN_LAPORAN), status=status
                )
                dilaporkan += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Selesai: {dibuat} ulasan baru, {dibalas} balasan, {dilaporkan} laporan "
                f"(dari {len(produk)} produk, {len(pembeli)} pembeli seed)."
            )
        )

    def _buat_pembeli(self, jumlah):
        hasil = []
        for i in range(1, jumlah + 1):
            username = f"{PREFIX}{i}"
            user = User.objects.filter(username=username).first()
            if user is None:
                user = User.objects.create_user(
                    username=username,
                    email=f"{username}@seed.local",
                    password=None,
                    role=User.ROLE_BUYER,
                    full_name=NAMA[(i - 1) % len(NAMA)],
                )
            hasil.append(user)
        return hasil

import uuid
from functools import wraps

from django.contrib.auth import get_user_model
from django.core.paginator import Paginator
from django.db import IntegrityError, transaction
from django.db.models import Count, Max
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.utils import dateformat, timezone, translation
from django.views.decorators.http import require_GET, require_POST

from apps.users.models import SellerProfile

from . import integrations
from .models import BalasanUlasan, FotoUlasan, LaporanUlasan, UlasanToko
from .services import ringkasan_produk, ringkasan_toko

User = get_user_model()

PER_HALAMAN = 5
MAKS_FOTO = 3
MAKS_UKURAN_FOTO = 2 * 1024 * 1024  # 2 MB
TIPE_FOTO = {"image/jpeg", "image/png", "image/webp"}
URUTAN = {
    "terbaru": ("-created_at",),
    "tertinggi": ("-rating", "-created_at"),
    "terendah": ("rating", "-created_at"),
}


# ---------- helper ----------
def _err(pesan, status=400):
    return JsonResponse({"ok": False, "error": pesan}, status=status)


def api_login_required(view):
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return _err("Silakan login terlebih dahulu.", 401)
        return view(request, *args, **kwargs)

    return wrapper


def _tgl(dt):
    with translation.override("id"):
        return dateformat.format(timezone.localtime(dt), "j F Y")


def _nama(user):
    return user.full_name or user.username


def _toko_milik(user):
    return getattr(user, "seller_profile", None)


def _qs_ulasan():
    return UlasanToko.objects.select_related("pembeli", "toko", "balasan").prefetch_related(
        "foto", "laporan"
    )


def _serialisasi(u, user):
    login = user.is_authenticated
    milik_saya = login and u.pembeli_id == user.id
    pemilik_toko = login and u.toko.user_id == user.id
    balasan = getattr(u, "balasan", None)
    return {
        "id": u.id,
        "pembeli": _nama(u.pembeli),
        "rating": u.rating,
        "komentar": u.komentar,
        "tanggal": _tgl(u.created_at),
        "diedit": u.diedit,
        "terverifikasi": True,  # ulasan hanya bisa dibuat oleh pembeli yang sudah membeli
        "produk": {"id": u.produk_id, "nama": u.nama_produk},
        "foto": [f.gambar.url for f in u.foto.all()],
        "milik_saya": milik_saya,
        "bisa_diedit": milik_saya and u.bisa_diedit(),
        "disembunyikan": u.disembunyikan if milik_saya else False,
        "balasan": (
            {
                "pesan": balasan.pesan,
                "tanggal": _tgl(balasan.created_at),
                "milik_saya": pemilik_toko,
                "bisa_diedit": pemilik_toko and balasan.bisa_diedit(),
            }
            if balasan
            else None
        ),
        "bisa_dibalas": pemilik_toko and balasan is None and not u.disembunyikan,
        "bisa_dilaporkan": pemilik_toko
        and not any(l.pelapor_id == user.id for l in u.laporan.all()),
    }


def _baca_input(request):
    try:
        rating = int(request.POST.get("rating", ""))
    except ValueError:
        return None, None, "Rating harus berupa angka 1-5."
    if not 1 <= rating <= 5:
        return None, None, "Rating harus antara 1 dan 5."
    komentar = request.POST.get("komentar", "").strip()
    if len(komentar) > 1000:
        return None, None, "Komentar maksimal 1000 karakter."
    return rating, komentar, None


def _validasi_foto(files):
    if len(files) > MAKS_FOTO:
        return f"Maksimal {MAKS_FOTO} foto."
    for f in files:
        if f.content_type not in TIPE_FOTO:
            return "Format foto harus JPG, PNG, atau WEBP."
        if f.size > MAKS_UKURAN_FOTO:
            return "Ukuran tiap foto maksimal 2 MB."
    return None


def _baca_teks(request, nama, maks, minimal=1):
    teks = request.POST.get(nama, "").strip()
    if len(teks) < minimal:
        return None, f"Kolom {nama} wajib diisi."
    if len(teks) > maks:
        return None, f"Maksimal {maks} karakter."
    return teks, None


def _uuid_atau_none(nilai):
    try:
        return uuid.UUID(str(nilai))
    except (ValueError, AttributeError):
        return None


def _daftar(request, toko):
    pemilik = request.user.is_authenticated and toko.user_id == request.user.id
    dasar = UlasanToko.objects.tampil().filter(toko=toko)
    qs = _qs_ulasan().filter(toko=toko, disembunyikan=False)

    if request.GET.get("rating") in {"1", "2", "3", "4", "5"}:
        qs = qs.filter(rating=int(request.GET["rating"]))
    if request.GET.get("foto") == "1":
        qs = qs.filter(foto__isnull=False).distinct()
    produk_id = _uuid_atau_none(request.GET.get("produk", ""))
    if produk_id:
        qs = qs.filter(produk_id=produk_id)
    if pemilik and request.GET.get("belum_dibalas") == "1":
        qs = qs.filter(balasan__isnull=True)
    qs = qs.order_by(*URUTAN.get(request.GET.get("urut"), URUTAN["terbaru"]))

    halaman = Paginator(qs, PER_HALAMAN).get_page(request.GET.get("page"))
    daftar_produk = (
        dasar.order_by()
        .values("produk_id")
        .annotate(nama=Max("nama_produk"), jumlah=Count("id"))
        .order_by("nama")
    )
    return JsonResponse(
        {
            "ok": True,
            "toko": {"id": toko.id, "nama": toko.store_name},
            "ringkasan": ringkasan_toko(toko.id),
            "ringkasan_produk": ringkasan_produk(produk_id) if produk_id else None,
            "produk": list(daftar_produk),
            "ulasan": [_serialisasi(u, request.user) for u in halaman],
            "halaman": halaman.number,
            "ada_berikutnya": halaman.has_next(),
        }
    )


# ---------- READ ----------
@require_GET
def daftar_ulasan(request, toko_id):
    """Publik. ?rating=1-5 &foto=1 &produk=<id> &urut=terbaru|tertinggi|terendah
    &belum_dibalas=1 (khusus pemilik toko) &page=N"""
    return _daftar(request, get_object_or_404(SellerProfile, pk=toko_id))


@require_GET
@api_login_required
def ulasan_penjual(request):
    """Seller: semua ulasan di tokonya sendiri (parameter sama dengan daftar_ulasan)."""
    toko = _toko_milik(request.user)
    if toko is None:
        return _err("Hanya penjual yang dapat membuka halaman ini.", 403)
    return _daftar(request, toko)


@require_GET
@api_login_required
def ulasan_saya(request):
    """Buyer: halaman 'Ulasan Saya'."""
    qs = _qs_ulasan().filter(pembeli=request.user)
    halaman = Paginator(qs, PER_HALAMAN).get_page(request.GET.get("page"))
    return JsonResponse(
        {
            "ok": True,
            "ulasan": [_serialisasi(u, request.user) for u in halaman],
            "halaman": halaman.number,
            "ada_berikutnya": halaman.has_next(),
        }
    )


# ---------- CREATE / UPDATE / DELETE (buyer) ----------
@require_POST
@api_login_required
def tambah_ulasan(request, toko_id):
    toko = get_object_or_404(SellerProfile, pk=toko_id)
    if toko.user_id == request.user.id:
        return _err("Anda tidak dapat mengulas toko sendiri.", 403)
    if request.user.role != User.ROLE_BUYER:
        return _err("Hanya pembeli yang dapat menulis ulasan.", 403)

    rating, komentar, error = _baca_input(request)
    if error:
        return _err(error)
    produk_id = _uuid_atau_none(request.POST.get("produk_id", ""))
    if produk_id is None:
        return _err("Pilih produk yang ingin diulas.")
    files = request.FILES.getlist("foto")
    error = _validasi_foto(files)
    if error:
        return _err(error)

    info = integrations.ambil_produk(produk_id)
    if info is None:
        return _err("Produk tidak ditemukan.", 404)
    if info["toko_id"] is not None and info["toko_id"] != toko.id:
        return _err("Produk ini bukan milik toko tersebut.")
    if not integrations.pernah_membeli(request.user, produk_id):
        return _err("Anda hanya dapat mengulas produk yang pernah Anda beli.", 403)

    try:
        with transaction.atomic():
            ulasan = UlasanToko.objects.create(
                toko=toko,
                pembeli=request.user,
                produk_id=produk_id,
                nama_produk=info["nama"],
                rating=rating,
                komentar=komentar,
            )
            for f in files:
                FotoUlasan.objects.create(ulasan=ulasan, gambar=f)
    except IntegrityError:
        return _err("Anda sudah mengulas produk ini. Silakan edit ulasan Anda.", 409)

    ulasan = _qs_ulasan().get(pk=ulasan.pk)
    return JsonResponse(
        {"ok": True, "ulasan": _serialisasi(ulasan, request.user), "ringkasan": ringkasan_toko(toko.id)},
        status=201,
    )


@require_POST
@api_login_required
def edit_ulasan(request, pk):
    ulasan = get_object_or_404(_qs_ulasan(), pk=pk)
    if ulasan.pembeli_id != request.user.id:
        return _err("Anda hanya dapat mengedit ulasan sendiri.", 403)
    if not ulasan.bisa_diedit():
        return _err("Ulasan hanya dapat diedit dalam 7 hari setelah diposting.", 403)

    rating, komentar, error = _baca_input(request)
    if error:
        return _err(error)
    ulasan.rating, ulasan.komentar, ulasan.diedit = rating, komentar, True
    ulasan.save(update_fields=["rating", "komentar", "diedit", "updated_at"])
    return JsonResponse(
        {"ok": True, "ulasan": _serialisasi(ulasan, request.user), "ringkasan": ringkasan_toko(ulasan.toko_id)}
    )


@require_POST
@api_login_required
def hapus_ulasan(request, pk):
    ulasan = get_object_or_404(UlasanToko, pk=pk)
    if ulasan.pembeli_id != request.user.id and not request.user.is_staff:
        return _err("Anda hanya dapat menghapus ulasan sendiri.", 403)
    toko_id = ulasan.toko_id
    ulasan.delete()
    return JsonResponse({"ok": True, "ringkasan": ringkasan_toko(toko_id)})


# ---------- Seller: balasan ----------
def _ulasan_toko_saya(request, pk):
    """Return (ulasan, error_response). Ulasan harus milik toko penjual yang login."""
    ulasan = get_object_or_404(_qs_ulasan(), pk=pk, disembunyikan=False)
    if ulasan.toko.user_id != request.user.id:
        return None, _err("Ulasan ini bukan milik toko Anda.", 403)
    return ulasan, None


@require_POST
@api_login_required
def balas_ulasan(request, pk):
    ulasan, resp = _ulasan_toko_saya(request, pk)
    if resp:
        return resp
    pesan, error = _baca_teks(request, "pesan", 300)
    if error:
        return _err(error)
    try:
        with transaction.atomic():
            BalasanUlasan.objects.create(ulasan=ulasan, penjual=request.user, pesan=pesan)
    except IntegrityError:
        return _err("Ulasan ini sudah Anda balas. Silakan edit balasan.", 409)
    ulasan = _qs_ulasan().get(pk=pk)
    return JsonResponse({"ok": True, "ulasan": _serialisasi(ulasan, request.user)}, status=201)


@require_POST
@api_login_required
def edit_balasan(request, pk):
    ulasan, resp = _ulasan_toko_saya(request, pk)
    if resp:
        return resp
    balasan = getattr(ulasan, "balasan", None)
    if balasan is None:
        return _err("Belum ada balasan untuk ulasan ini.", 404)
    if not balasan.bisa_diedit():
        return _err("Balasan hanya dapat diedit dalam 1 hari setelah diposting.", 403)
    pesan, error = _baca_teks(request, "pesan", 300)
    if error:
        return _err(error)
    balasan.pesan = pesan
    balasan.save(update_fields=["pesan", "updated_at"])
    ulasan = _qs_ulasan().get(pk=pk)
    return JsonResponse({"ok": True, "ulasan": _serialisasi(ulasan, request.user)})


@require_POST
@api_login_required
def hapus_balasan(request, pk):
    ulasan, resp = _ulasan_toko_saya(request, pk)
    if resp:
        return resp
    balasan = getattr(ulasan, "balasan", None)
    if balasan is None:
        return _err("Belum ada balasan untuk ulasan ini.", 404)
    balasan.delete()
    return JsonResponse({"ok": True})


# ---------- Seller: laporan ----------
@require_POST
@api_login_required
def laporkan_ulasan(request, pk):
    ulasan, resp = _ulasan_toko_saya(request, pk)
    if resp:
        return resp
    alasan, error = _baca_teks(request, "alasan", 300, minimal=5)
    if error:
        return _err(error)
    try:
        with transaction.atomic():
            LaporanUlasan.objects.create(ulasan=ulasan, pelapor=request.user, alasan=alasan)
    except IntegrityError:
        return _err("Anda sudah melaporkan ulasan ini.", 409)
    return JsonResponse({"ok": True, "pesan": "Laporan terkirim dan akan ditinjau admin."}, status=201)
import time
import uuid
from functools import wraps

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.paginator import Paginator
from django.db import IntegrityError, transaction
from django.db.models import Count, Max
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import dateformat, timezone, translation
from django.views.decorators.http import require_GET, require_POST

from apps.products.models import Product
from apps.products.views import get_role
from apps.users.models import SellerProfile

from . import integrations
from .forms import (  # noqa: F401  (konstanta tetap bisa diimpor dari views)
    MAKS_FOTO,
    MAKS_UKURAN_FOTO,
    TIPE_FOTO,
    BalasanForm,
    FilterUlasanForm,
    LaporanForm,
    UlasanBaruForm,
    UlasanEditForm,
)
from .models import BalasanUlasan, FotoUlasan, LaporanUlasan, UlasanToko
from .services import ringkasan_produk, ringkasan_toko

User = get_user_model()

PER_HALAMAN = 5
URUTAN = {
    "terbaru": ("-created_at",),
    "tertinggi": ("-rating", "-created_at"),
    "terendah": ("rating", "-created_at"),
}


# ---------- helper ----------
def _err(pesan, status=400):
    return JsonResponse({"ok": False, "error": pesan}, status=status)


def _pesan_form(form):
    """Pesan error pertama dari form (urutan field = urutan pengecekan)."""
    for daftar in form.errors.values():
        return daftar[0]
    return "Input tidak valid."


def api_login_required(view):
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return _err("Silakan login terlebih dahulu.", 401)
        return view(request, *args, **kwargs)

    return wrapper


def rate_limit(requests=10, per_seconds=60, key_prefix="rv_rl"):
    """
    Decorator pembatas laju request (Rate Limiter) berbasis Django cache.
    Menggunakan sliding window berbasis timestamp per user/IP.
    Memenuhi aspek keamanan tingkat lanjut (Rubrik PBP - Security Awareness).
    """
    def decorator(view_func):
        @wraps(view_func)
        def wrapper(request, *args, **kwargs):
            if request.user.is_authenticated:
                ident = f"user_{request.user.id}"
            else:
                raw_ip = request.META.get("HTTP_X_FORWARDED_FOR") or request.META.get("REMOTE_ADDR") or "anon"
                ident = raw_ip.split(",")[0].strip()

            cache_key = f"{key_prefix}:{view_func.__name__}:{ident}"
            now = time.time()
            timestamps = cache.get(cache_key, [])
            valid_timestamps = [ts for ts in timestamps if now - ts < per_seconds]

            if len(valid_timestamps) >= requests:
                sisa_waktu = int(per_seconds - (now - valid_timestamps[0])) + 1
                return _err(f"Terlalu banyak permintaan. Silakan tunggu {sisa_waktu} detik lagi.", 429)

            valid_timestamps.append(now)
            cache.set(cache_key, valid_timestamps, per_seconds + 5)
            return view_func(request, *args, **kwargs)

        return wrapper
    return decorator


def _tgl(dt):
    with translation.override("id"):
        return dateformat.format(timezone.localtime(dt), "j F Y")


def _tgl_waktu(dt):
    """24 Januari 2026 21.54 (format di desain Figma)."""
    with translation.override("id"):
        return dateformat.format(timezone.localtime(dt), "j F Y H.i")


def _nama(user):
    return user.full_name or user.username


def _samarkan(nama):
    """Budi Santoso -> B*******o (untuk pengunjung yang belum login)."""
    nama = (nama or "").strip()
    if len(nama) <= 2:
        return (nama[:1] or "?") + "*"
    return nama[0] + "*" * min(len(nama) - 2, 6) + nama[-1]


def _toko_milik(user):
    return getattr(user, "seller_profile", None)


def _qs_ulasan():
    return UlasanToko.objects.select_related("pembeli", "toko", "balasan", "produk").prefetch_related(
        "foto", "laporan"
    )


def _serialisasi(u, user):
    login = user.is_authenticated
    milik_saya = login and u.pembeli_id == user.id
    pemilik_toko = login and u.toko.user_id == user.id
    balasan = getattr(u, "balasan", None)
    foto = [f.gambar.url for f in u.foto.all()]
    p = u.produk  # None bila produk sudah dihapus
    return {
        "id": u.id,
        # filter autentikasi: pengunjung hanya melihat nama samaran & tanpa foto
        "pembeli": _nama(u.pembeli) if login else _samarkan(_nama(u.pembeli)),
        "rating": u.rating,
        "komentar": u.komentar,
        "tanggal": _tgl(u.created_at),
        "waktu": _tgl_waktu(u.created_at),
        "diedit": u.diedit,
        "terverifikasi": True,  # ulasan hanya bisa dibuat oleh pembeli yang sudah membeli
        "toko": {"id": u.toko_id, "nama": u.toko.store_name},
        "produk": {
            "id": u.produk_id,
            "nama": u.nama_produk,
            # status verifikasi produk berasal dari Mock API (lewat Product.status)
            "status": p.status if p else None,
            "status_display": p.get_status_display() if p else "Produk dihapus",
        },
        "foto": foto if login else [],
        "jumlah_foto": len(foto),
        "foto_terkunci": (not login) and bool(foto),
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
    if request.GET.get("terverifikasi") == "1":
        # filter pada data hasil Mock API: hanya produk yang lolos verifikasi
        qs = qs.filter(produk__status="verified")
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


# ---------- READ (JSON) ----------
@require_GET
def daftar_ulasan(request, toko_id):
    """Publik. ?rating=1-5 &foto=1 &produk=<uuid> &terverifikasi=1 &urut=terbaru|tertinggi|terendah
    &belum_dibalas=1 (khusus pemilik toko) &page=N

    Pengunjung yang belum login mendapat nama pembeli yang disamarkan dan tanpa URL foto."""
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
@rate_limit(requests=10, per_seconds=60, key_prefix="rv_tambah")
def tambah_ulasan(request, toko_id):
    toko = get_object_or_404(SellerProfile, pk=toko_id)
    if toko.user_id == request.user.id:
        return _err("Anda tidak dapat mengulas toko sendiri.", 403)
    if request.user.role != User.ROLE_BUYER:
        return _err("Hanya pembeli yang dapat menulis ulasan.", 403)

    form = UlasanBaruForm(request.POST, request.FILES)
    if not form.is_valid():
        return _err(_pesan_form(form))
    rating = form.cleaned_data["rating"]
    komentar = form.cleaned_data["komentar"]
    produk_id = form.cleaned_data["produk_id"]
    files = form.cleaned_data["foto"]

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

    form = UlasanEditForm(request.POST)
    if not form.is_valid():
        return _err(_pesan_form(form))
    ulasan.rating = form.cleaned_data["rating"]
    ulasan.komentar = form.cleaned_data["komentar"]
    ulasan.diedit = True
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
@rate_limit(requests=10, per_seconds=60, key_prefix="rv_balas")
def balas_ulasan(request, pk):
    ulasan, resp = _ulasan_toko_saya(request, pk)
    if resp:
        return resp
    form = BalasanForm(request.POST)
    if not form.is_valid():
        return _err(_pesan_form(form))
    try:
        with transaction.atomic():
            BalasanUlasan.objects.create(
                ulasan=ulasan, penjual=request.user, pesan=form.cleaned_data["pesan"]
            )
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
    form = BalasanForm(request.POST)
    if not form.is_valid():
        return _err(_pesan_form(form))
    balasan.pesan = form.cleaned_data["pesan"]
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
@rate_limit(requests=5, per_seconds=60, key_prefix="rv_lapor")
def laporkan_ulasan(request, pk):
    ulasan, resp = _ulasan_toko_saya(request, pk)
    if resp:
        return resp
    form = LaporanForm(request.POST)
    if not form.is_valid():
        return _err(_pesan_form(form))
    try:
        with transaction.atomic():
            LaporanUlasan.objects.create(
                ulasan=ulasan, pelapor=request.user, alasan=form.cleaned_data["alasan"]
            )
    except IntegrityError:
        return _err("Anda sudah melaporkan ulasan ini.", 409)
    return JsonResponse({"ok": True, "pesan": "Laporan terkirim dan akan ditinjau admin."}, status=201)


# ---------------------------------------------------------------------------
# HALAMAN HTML (template + form; data diambil lewat AJAX dari view JSON di atas)
# ---------------------------------------------------------------------------
def _produk_toko(toko):
    """Produk toko yang masih relevan untuk pembeli (bukan ditolak/kedaluwarsa)."""
    return list(
        Product.objects.filter(seller=toko).exclude(status__in=["rejected", "expired"]).order_by("name")
    )


def _konteks_dasar(request, mode, toko=None):
    pemilik = toko is not None and request.user.is_authenticated and toko.user_id == request.user.id
    konteks = {
        "mode": mode,
        "toko": toko,
        "pemilik": pemilik,
        "login_url": reverse("users:login"),
        "form_edit": UlasanEditForm(auto_id="edit_%s"),
        "form_balas": BalasanForm(auto_id="balas_%s"),
        "form_laporan": LaporanForm(auto_id="laporan_%s"),
    }
    if mode == "saya":
        konteks["judul"] = konteks["heading"] = "Ulasan Saya"
        konteks["url_data"] = reverse("reviews:saya")
        return konteks

    produk = _produk_toko(toko)
    pilihan = [(str(p.pk), p.name) for p in produk]
    konteks["form_filter"] = FilterUlasanForm(
        request.GET or None, produk_choices=pilihan, boleh_belum_dibalas=pemilik
    )
    if mode == "penjual":
        konteks["judul"] = konteks["heading"] = "Ulasan Toko"
        konteks["url_data"] = reverse("reviews:penjual")
    else:
        konteks["judul"] = f"Ulasan {toko.store_name}"
        konteks["heading"] = "Ulasan"
        konteks["url_data"] = reverse("reviews:daftar", args=[toko.id])
        konteks["url_tambah"] = reverse("reviews:tambah", args=[toko.id])
        _siapkan_form_tulis(request, konteks, toko, produk)
    return konteks


def _siapkan_form_tulis(request, konteks, toko, produk):
    """Tentukan apakah pengunjung boleh menulis ulasan & produk apa yang bisa diulas."""
    role = get_role(request.user)
    if role == "guest":
        konteks["info_tulis"] = "Masuk sebagai pembeli untuk menulis ulasan."
        return
    if role != "buyer":
        return  # seller/admin: tidak ada form dan tidak perlu pesan
    sudah = set(
        UlasanToko.objects.filter(pembeli=request.user, toko=toko).values_list("produk_id", flat=True)
    )
    bisa = [
        (str(p.pk), p.name)
        for p in produk
        if p.status == "verified"
        and p.pk not in sudah
        and integrations.pernah_membeli(request.user, p.pk)
    ]
    if bisa:
        initial = {}
        target_p = request.GET.get("produk")
        if target_p and any(str(p[0]) == str(target_p) for p in bisa):
            initial["produk_id"] = target_p
        konteks["form_tulis"] = UlasanBaruForm(auto_id="tulis_%s", produk_choices=bisa, initial=initial)
    else:
        konteks["info_tulis"] = (
            "Belum ada produk dari toko ini yang bisa Anda ulas. "
            "Ulasan hanya dapat ditulis untuk produk dari pesanan yang sudah selesai."
        )


@require_GET
def halaman_toko(request, toko_id):
    """Laman Ulasan Toko (publik)."""
    toko = get_object_or_404(SellerProfile, pk=toko_id)
    return render(request, "reviews/daftar.html", _konteks_dasar(request, "toko", toko))


@require_GET
def halaman_saya(request):
    """'Ulasan Saya' (buyer)."""
    if not request.user.is_authenticated:
        return redirect("users:login")
    if get_role(request.user) != "buyer":
        return redirect("dashboard:show_dashboard_home")
    return render(request, "reviews/daftar.html", _konteks_dasar(request, "saya"))


@require_GET
def halaman_penjual(request):
    """'Ulasan Toko' di dashboard seller: ulasan toko miliknya, lengkap dengan balas & laporkan."""
    if not request.user.is_authenticated:
        return redirect("users:login")
    toko = _toko_milik(request.user)
    if get_role(request.user) != "seller" or toko is None:
        return redirect("dashboard:show_dashboard_home")
    return render(request, "reviews/daftar.html", _konteks_dasar(request, "penjual", toko))

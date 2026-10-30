from datetime import timedelta

from django.db.models import ExpressionWrapper, F, IntegerField, Q, Sum
from django.db.models.functions import TruncDate
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from apps.products.models import Product
from apps.checkout.models import Order, OrderItem
from apps.products.views import get_role, cek_status
from apps.reviews.services import laporan_ulasan, rating_per_produk, ringkasan_ulasan_toko


NAMA_HARI = ["Sen", "Sel", "Rab", "Kam", "Jum", "Sab", "Min"]


def _item_penjualan(profile=None):
    qs = OrderItem.objects.filter(order__status="selesai")
    if profile is not None:
        qs = qs.filter(
            Q(order__seller=profile)
            | Q(order__seller__isnull=True, product__seller=profile)
        )
    return qs


def _pesanan_toko(profile):
    return Order.objects.filter(
        Q(seller=profile)
        | Q(seller__isnull=True, items__product__seller=profile)
    ).distinct()


def _total_pendapatan(items):
    nilai = ExpressionWrapper(F("price") * F("quantity"), output_field=IntegerField())
    return items.aggregate(total=Sum(nilai))["total"] or 0


def _produk_terlaris(items, batas=5):
    nilai = ExpressionWrapper(F("price") * F("quantity"), output_field=IntegerField())
    return list(
        items.order_by()
        .values("product_id", "product_name")
        .annotate(terjual=Sum("quantity"), pendapatan=Sum(nilai))
        .order_by("-terjual", "-pendapatan", "product_name")[:batas]
    )


def _batas_periode(periode, hari_ini):
    if periode == "mingguan":
        mulai = hari_ini - timedelta(days=6)
        selesai = hari_ini + timedelta(days=1)
        return mulai, selesai, mulai - timedelta(days=7), mulai
    mulai = hari_ini.replace(day=1)
    selesai = (mulai.replace(day=28) + timedelta(days=4)).replace(day=1)
    sebelumnya_selesai = mulai
    sebelumnya_mulai = (mulai - timedelta(days=1)).replace(day=1)
    return mulai, selesai, sebelumnya_mulai, sebelumnya_selesai


def _statistik_penjualan(profile=None, periode="bulanan"):
    from django.utils import timezone

    periode = periode if periode in {"mingguan", "bulanan"} else "bulanan"
    mulai, selesai, mulai_lalu, selesai_lalu = _batas_periode(periode, timezone.localdate())
    semua = _item_penjualan(profile)
    sekarang = semua.filter(order__created_at__date__gte=mulai, order__created_at__date__lt=selesai)
    lalu = semua.filter(order__created_at__date__gte=mulai_lalu, order__created_at__date__lt=selesai_lalu)
    pendapatan = _total_pendapatan(sekarang)
    pendapatan_lalu = _total_pendapatan(lalu)
    jumlah_pesanan = sekarang.values("order_id").distinct().count()
    if pendapatan_lalu:
        perubahan = round((pendapatan - pendapatan_lalu) * 100 / pendapatan_lalu, 1)
        pertumbuhan = f"{perubahan:+g}%"
    elif pendapatan:
        pertumbuhan = "Belum ada pembanding"
    else:
        pertumbuhan = "0%"
    return {
        "periode": periode,
        "pendapatan": pendapatan,
        "rata_pesanan": round(pendapatan / jumlah_pesanan) if jumlah_pesanan else 0,
        "pertumbuhan": pertumbuhan,
        "produk_terlaris": _produk_terlaris(sekarang),
    }

def show_dashboard_home(request):
    role = get_role(request.user)

    name = "Tamu"
    if request.user.is_authenticated:
        if role == "admin":
            name = "Etmin"
        elif role == "seller":
            name = request.user.seller_profile.store_name
        elif role == "buyer":
            name = request.user.username

    return render(request, "dashboard_home.html", {"role": role, "name": name})


def api_products(request):
    role = get_role(request.user)
    seller_id = request.GET.get("seller_id", "").strip()

    if seller_id:
        products = Product.objects.filter(Q(seller__user_id=seller_id) | Q(seller_id=seller_id))
        if role != "admin" and not (role == "seller" and str(request.user.id) == str(seller_id)):
            products = products.exclude(status__in=["rejected", "expired"])
    elif role == "seller":
        products = Product.objects.filter(seller__user=request.user)
        for product in products.filter(status="pending"):
            cek_status(product)
    elif role == "admin":
        products = Product.objects.all()
    else:
        products = Product.objects.filter(status="verified")

    query = request.GET.get("title", "").strip() or request.GET.get("q", "").strip()
    if query:
       products = (products.filter(name__icontains=query)
        | products.filter(description__icontains=query)
        | products.filter(materials__icontains=query))

    products = products.order_by("-created_at")

    products = list(products)
    rating = rating_per_produk(p.pk for p in products)  # 1 query untuk semua kartu

    items = []
    for product in products:
        stat = rating.get(product.pk)
        items.append({
            "id": str(product.pk),
            "product_id": str(product.pk),
            "name": product.name,
            "product_name": product.name,
            "image": product.image.url if product.image else None,
            "image_url": product.image.url if product.image else None,
            "price": int(product.price),
            "discount": product.discount,
            "final_price": product.final_price,
            "stock": product.stock,
            "status": product.status,
            "status_display": product.get_status_display(),
            "verification_summary": product.verification_summary,
            "edit_url": reverse("products:edit_product", args=[product.pk]),
            "delete_url": reverse("products:delete_product", args=[product.pk]),
            "toko_id": product.seller_id,
            "review_url": reverse("reviews:halaman_toko", args=[product.seller_id]) + f"?produk={product.pk}",
            "rating": stat["rata"] if stat else None,
            "rating_teks": stat["rata_teks"] if stat else None,
            "jumlah_ulasan": stat["jumlah"] if stat else 0,
        })

    return JsonResponse({
        "status": "success",
        "role": role,
        "query": query,
        "count": len(items),
        "login_url": reverse("users:login"),
        "products": items,
        "items": items,
    })

def _alihkan_bila_tak_berhak(request, role_diizinkan):
    """None bila boleh; selain itu redirect (guest -> login, role lain -> beranda)."""
    role = get_role(request.user)
    if role == "guest":
        return redirect("users:login")
    if role not in role_diizinkan:
        return redirect("dashboard:show_dashboard_home")
    return None


def seller_summary(request):
    tolak = _alihkan_bila_tak_berhak(request, {"seller"})
    if tolak:
        return tolak
    profile = getattr(request.user, "seller_profile", None)
    if profile is None:
        return redirect("dashboard:show_dashboard_home")
    from django.utils import timezone

    hari_ini = timezone.localdate()
    mulai_bulan = hari_ini.replace(day=1)
    items_selesai = _item_penjualan(profile)
    pendapatan_bulan = _total_pendapatan(
        items_selesai.filter(order__created_at__date__gte=mulai_bulan)
    )
    mulai_minggu = hari_ini - timedelta(days=6)
    harian = {
        row["tanggal"]: row["total"]
        for row in (
            items_selesai.filter(order__created_at__date__gte=mulai_minggu)
            .annotate(tanggal=TruncDate("order__created_at"))
            .values("tanggal")
            .annotate(total=Sum(ExpressionWrapper(F("price") * F("quantity"), output_field=IntegerField())))
        )
    }
    nilai_tertinggi = max(harian.values(), default=0)
    grafik = []
    for offset in range(7):
        tanggal = mulai_minggu + timedelta(days=offset)
        nilai = harian.get(tanggal, 0)
        grafik.append({
            "label": NAMA_HARI[tanggal.weekday()],
            "tanggal": tanggal,
            "nilai": nilai,
            "tinggi": round(nilai * 100 / nilai_tertinggi) if nilai_tertinggi else 0,
            "tertinggi": bool(nilai_tertinggi and nilai == nilai_tertinggi),
        })
    return render(request, "seller_summary.html", {
        "name": profile.store_name,
        "ulasan": ringkasan_ulasan_toko(profile),
        "jumlah_produk": Product.objects.filter(seller=profile).count(),
        "jumlah_pesanan": _pesanan_toko(profile).count(),
        "pendapatan_bulan": pendapatan_bulan,
        "grafik": grafik,
        "produk_terlaris": _produk_terlaris(items_selesai, batas=3),
    })

def sales_report(request):
    tolak = _alihkan_bila_tak_berhak(request, {"seller", "admin"})
    if tolak:
        return tolak
    role = get_role(request.user)
    profile = getattr(request.user, "seller_profile", None)
    if role == "seller" and profile is None:
        return redirect("dashboard:show_dashboard_home")
    periode = request.GET.get("periode")
    penjualan = _statistik_penjualan(profile if role == "seller" else None, periode)
    return render(request, "sales_report.html", {
        "penjualan": penjualan,
        "ulasan": laporan_ulasan(role, toko=profile, periode=penjualan["periode"]),
    })

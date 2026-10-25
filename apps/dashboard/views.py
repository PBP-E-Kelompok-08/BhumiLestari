from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from apps.products.models import Product
from apps.products.views import get_role, cek_status
from apps.reviews.services import laporan_ulasan, ringkasan_ulasan_toko

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

    items = []
    for product in products:
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
    return render(request, "seller_summary.html", {
        "name": profile.store_name,
        "ulasan": ringkasan_ulasan_toko(profile),
    })

def sales_report(request):
    tolak = _alihkan_bila_tak_berhak(request, {"seller", "admin"})
    if tolak:
        return tolak
    role = get_role(request.user)
    profile = getattr(request.user, "seller_profile", None)
    if role == "seller" and profile is None:
        return redirect("dashboard:show_dashboard_home")
    return render(request, "sales_report.html", {
        "ulasan": laporan_ulasan(role, toko=profile, periode=request.GET.get("periode")),
    })

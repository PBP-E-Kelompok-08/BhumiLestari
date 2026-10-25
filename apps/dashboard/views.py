from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import render
from django.urls import reverse
from apps.products.models import Product
from apps.products.views import get_role, cek_status

def show_dashboard_home(request):
    role = get_role(request.user)

    name = "Tamu"
    if request.user.is_authenticated:
        if role == "admin":
            name = "Etmin"
        elif role == "seller":
            name = request.user.seller_profile.store_name
        elif role == "buyer":
            name = request.user.full_name

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
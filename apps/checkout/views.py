from django.contrib.auth.decorators import login_required
from django.db.models import Sum
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_POST

from apps.checkout.models import Cart, CartItem
from apps.products.models import Product


def get_cart_data(request):
    cart, _ = Cart.objects.get_or_create(user=request.user)
    cart_items = cart.items.select_related("product", "product__seller")

    stores = {}
    for ci in cart_items:
        product = ci.product
        store = stores.setdefault(
            product.seller_id, {"name": product.seller.store_name, "items": []}
        )
        store["items"].append({
            "id": ci.pk,
            "name": product.name,
            "variation": "Standar",
            "price": int(product.price),
            "discount": product.discount,
            "final_price": int(product.final_price),
            "quantity": ci.quantity,
            "selected": ci.is_selected,
            "image_url": product.image.url if product.image else "",
            "stock": product.stock,
        })
    return list(stores.values())


@login_required(login_url="users:login")
def show_cart(request):
    stores = get_cart_data(request)

    total = 0
    item_count = 0
    selected_count = 0
    for store in stores:
        for item in store["items"]:
            item_count += item["quantity"]
            if item["selected"]:
                total += item["final_price"] * item["quantity"]
                selected_count += 1

    context = {
        "stores": stores,
        "total": total,
        "item_count": item_count,
        "selected_count": selected_count,
    }
    return render(request, "cart.html", context)


@require_POST
def add_to_cart(request, product_id):
    # Tamu -> 401 JSON (bukan redirect HTML)
    if not request.user.is_authenticated:
        return JsonResponse({"ok": False, "error": "Silakan login dulu."}, status=401)
    if getattr(request.user, "role", None) != "buyer":
        return JsonResponse({"ok": False, "error": "Hanya pembeli yang bisa belanja."}, status=403)

    product = Product.objects.filter(pk=product_id, status="verified").first()
    if product is None:
        return JsonResponse({"ok": False, "error": "Produk tidak ditemukan."}, status=404)

    cart, _ = Cart.objects.get_or_create(user=request.user)
    item = CartItem.objects.filter(cart=cart, product=product).first()
    current = item.quantity if item else 0

    if current + 1 > product.stock:
        return JsonResponse({"ok": False, "error": "Stok tidak mencukupi."}, status=400)

    if item:
        item.quantity = current + 1
        item.save(update_fields=["quantity"])
    else:
        CartItem.objects.create(cart=cart, product=product, quantity=1)

    cart_count = cart.items.aggregate(n=Sum("quantity"))["n"] or 0
    return JsonResponse({"ok": True, "cart_count": cart_count})


@login_required(login_url="users:login")
def show_checkout(request):
    context = {
        "recipient_name": "Nama Penerima",
        "address": "Alamat pengiriman",
        "shipping_options": ["Reguler", "Kargo", "Express", "Same Day"],
        "payment_options": ["E-Wallet", "QRIS", "Transfer Bank", "Cash On Delivery"],
        "items_total": 18000,
        "shipping_cost": 5000,
        "grand_total": 23000,
        "item_count": 2,
    }
    return render(request, "checkout.html", context)

def order_list(request):
    return render(request, "order_list.html")


def order_detail(request):
    return render(request, "order_detail.html")
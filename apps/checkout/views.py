import json

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
    selected_count = 0
    line_count = 0
    for store in stores:
        for item in store["items"]:
            line_count += 1
            if item["selected"]:
                total += item["final_price"] * item["quantity"]
                selected_count += item["quantity"]

    context = {
        "stores": stores,
        "total": total,
        "line_count": line_count,
        "selected_count": selected_count,
    }
    return render(request, "cart.html", context)


## Helper untuk endpoint JSON keranjang 

def _buyer_cart(request):
    """Return (cart, None) kalau boleh, atau (None, JsonResponse error)."""
    if not request.user.is_authenticated:
        return None, JsonResponse({"ok": False, "error": "Silakan login dulu."}, status=401)
    if getattr(request.user, "role", None) != "buyer":
        return None, JsonResponse({"ok": False, "error": "Hanya pembeli yang bisa belanja."}, status=403)
    cart, _ = Cart.objects.get_or_create(user=request.user)
    return cart, None


def _read_json(request):
    try:
        data = json.loads(request.body or b"{}")
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def _int_list(value):
    if not isinstance(value, list):
        return []
    return [v for v in value if isinstance(v, int) and not isinstance(v, bool)]


## Create 

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


## Update

@require_POST
def update_cart_item(request, item_id):
    cart, error = _buyer_cart(request)
    if error:
        return error

    item = CartItem.objects.select_related("product").filter(pk=item_id, cart=cart).first()
    if item is None:
        return JsonResponse({"ok": False, "error": "Item tidak ditemukan."}, status=404)

    quantity = _read_json(request).get("quantity")
    if not isinstance(quantity, int) or isinstance(quantity, bool) or quantity < 1:
        return JsonResponse({"ok": False, "error": "Jumlah tidak valid."}, status=400)
    if quantity > item.product.stock:
        return JsonResponse(
            {"ok": False, "error": f"Stok tidak mencukupi (sisa {item.product.stock})."},
            status=400,
        )

    item.quantity = quantity
    item.save(update_fields=["quantity"])
    return JsonResponse({"ok": True, "quantity": quantity})


@require_POST
def select_cart_items(request):
    """Terima daftar id yang TERCENTANG; sisanya otomatis jadi tidak tercentang."""
    cart, error = _buyer_cart(request)
    if error:
        return error

    ids = _int_list(_read_json(request).get("selected_ids"))
    cart.items.filter(pk__in=ids).update(is_selected=True)
    cart.items.exclude(pk__in=ids).update(is_selected=False)
    return JsonResponse({"ok": True})


## Delete 

@require_POST
def delete_cart_items(request):
    cart, error = _buyer_cart(request)
    if error:
        return error

    ids = _int_list(_read_json(request).get("ids"))
    if not ids:
        return JsonResponse({"ok": False, "error": "Tidak ada item dipilih."}, status=400)

    cart.items.filter(pk__in=ids).delete()
    cart_count = cart.items.aggregate(n=Sum("quantity"))["n"] or 0
    return JsonResponse({"ok": True, "cart_count": cart_count})


## Checkout (dummy}

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
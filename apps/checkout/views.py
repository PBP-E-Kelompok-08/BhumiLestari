import json

from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Sum
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from apps.checkout.models import Cart, CartItem, Order, OrderItem
from apps.products.models import Product

# Ongkir
SHIPPING = {
    "reguler": ("Reguler", 7000),
    "kargo": ("Kargo", 15000),
    "express": ("Express", 20000),
    "same_day": ("Same Day", 30000),
}
PAYMENT = {
    "ewallet": "E-Wallet",
    "qris": "QRIS",
    "transfer": "Transfer Bank",
    "cod": "Cash On Delivery",
}


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


# Helper endpoint JSON keranjang

def _buyer_cart(request):
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


# Create

@require_POST
def add_to_cart(request, product_id):
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


# Update

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
    cart, error = _buyer_cart(request)
    if error:
        return error

    ids = _int_list(_read_json(request).get("selected_ids"))
    cart.items.filter(pk__in=ids).update(is_selected=True)
    cart.items.exclude(pk__in=ids).update(is_selected=False)
    return JsonResponse({"ok": True})


# Delete

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


# Checkout

def _create_order(user, recipient, phone, address, shipping_key, payment_key):
    """Buat Order + OrderItem, kurangi stok, hapus item terpilih. Raise ValueError kalau gagal."""
    with transaction.atomic():
        cart = Cart.objects.get(user=user)
        items = list(cart.items.filter(is_selected=True))
        if not items:
            raise ValueError("Tidak ada barang yang dipilih.")

        products = {
            p.pk: p
            for p in Product.objects.select_for_update().filter(
                pk__in=[ci.product_id for ci in items]
            )
        }

        items_total = 0
        for ci in items:
            p = products[ci.product_id]
            if p.status != "verified":
                raise ValueError(f"{p.name} sudah tidak tersedia.")
            if ci.quantity > p.stock:
                raise ValueError(f"Stok {p.name} tidak mencukupi (sisa {p.stock}).")
            items_total += int(p.final_price) * ci.quantity

        shipping_cost = SHIPPING[shipping_key][1]
        order = Order.objects.create(
            buyer=user,
            recipient_name=recipient,
            phone=phone,
            shipping_address=address,
            shipping_method=shipping_key,
            payment_method=payment_key,
            shipping_cost=shipping_cost,
            total_price=items_total + shipping_cost,
        )

        for ci in items:
            p = products[ci.product_id]
            OrderItem.objects.create(
                order=order,
                product=p,
                product_name=p.name,
                price=int(p.final_price),
                quantity=ci.quantity,
            )
            p.stock -= ci.quantity
            p.save(update_fields=["stock"])

        cart.items.filter(pk__in=[ci.pk for ci in items]).delete()
    return order


@login_required(login_url="users:login")
def show_checkout(request):
    if getattr(request.user, "role", None) != "buyer":
        return redirect("dashboard:show_dashboard_home")

    cart, _ = Cart.objects.get_or_create(user=request.user)
    items = list(cart.items.filter(is_selected=True).select_related("product"))
    if not items:
        return redirect("checkout:show_cart")

    items_total = sum(int(ci.product.final_price) * ci.quantity for ci in items)
    item_count = sum(ci.quantity for ci in items)

    user = request.user
    form = {
        "recipient_name": getattr(user, "full_name", "") or "",
        "phone": getattr(user, "phone", "") or "",
        "address": getattr(user, "address", "") or "",
        "shipping_method": "reguler",
        "payment_method": "cod",
    }
    error = ""

    if request.method == "POST":
        form.update({
            "recipient_name": request.POST.get("recipient_name", "").strip(),
            "phone": request.POST.get("phone", "").strip(),
            "address": request.POST.get("address", "").strip(),
            "shipping_method": request.POST.get("shipping_method", ""),
            "payment_method": request.POST.get("payment_method", ""),
        })
        if not (form["recipient_name"] and form["phone"] and form["address"]):
            error = "Lengkapi alamat pengiriman dulu."
        elif form["shipping_method"] not in SHIPPING or form["payment_method"] not in PAYMENT:
            error = "Pilih opsi pengiriman dan metode pembayaran."
        else:
            try:
                _create_order(
                    request.user, form["recipient_name"], form["phone"], form["address"],
                    form["shipping_method"], form["payment_method"],
                )
            except ValueError as exc:
                error = str(exc)
            else:
                return redirect("checkout:order_list")

        if form["shipping_method"] not in SHIPPING:
            form["shipping_method"] = "reguler"
        if form["payment_method"] not in PAYMENT:
            form["payment_method"] = "cod"

    shipping_cost = SHIPPING[form["shipping_method"]][1]
    context = {
        "form": form,
        "error": error,
        "shipping_options": [
            {"key": k, "label": v[0], "cost": v[1]} for k, v in SHIPPING.items()
        ],
        "payment_options": [{"key": k, "label": v} for k, v in PAYMENT.items()],
        "items_total": items_total,
        "item_count": item_count,
        "shipping_cost": shipping_cost,
        "grand_total": items_total + shipping_cost,
    }
    return render(request, "checkout.html", context)


def order_list(request):
    return render(request, "order_list.html")


def order_detail(request):
    return render(request, "order_detail.html")
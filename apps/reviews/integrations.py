"""Titik sambung ke modul lain (Produk & Checkout).

Selama model Produk/Pesanan belum ada, STUB = True: produk dianggap ada dan
semua pembeli dianggap pernah membeli. Setelah modul lain jadi, set STUB = False
dan sesuaikan nama model/field di blok `else` (contoh di bawah hanya tebakan).
"""

STUB = True


def ambil_produk(produk_id):
    """Return {"nama": str, "toko_id": int|None} atau None bila produk tidak ada.
    toko_id = id SellerProfile pemilik produk (None = lewati pengecekan kepemilikan)."""
    if STUB:
        return {"nama": f"Produk #{produk_id}", "toko_id": None}
    from apps.products.models import Product  # sesuaikan

    p = Product.objects.filter(pk=produk_id).first()
    return {"nama": p.name, "toko_id": p.seller_id} if p else None


def pernah_membeli(user, produk_id):
    """True bila user punya pesanan SELESAI yang berisi produk tersebut."""
    if STUB:
        return True
    from apps.checkout.models import OrderItem  # sesuaikan

    return OrderItem.objects.filter(
        order__buyer=user, order__status="selesai", product_id=produk_id
    ).exists()
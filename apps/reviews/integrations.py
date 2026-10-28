"""Titik sambung ke modul lain (Produk & Checkout).

- Produk: sudah memakai model `products.Product` (primary key UUID).
- Pembelian: modul checkout belum punya model pesanan, jadi STUB_PEMBELIAN = True
  (semua pembeli dianggap pernah membeli). Setelah ada model pesanan, set ke False
  dan sesuaikan nama model/field di blok `else` (contoh di bawah hanya tebakan).
"""

STUB_PEMBELIAN = True


def ambil_produk(produk_id):
    """Return {"nama": str, "toko_id": int} atau None bila produk tidak ada.
    toko_id = id SellerProfile pemilik produk. produk_id berupa UUID."""
    from apps.products.models import Product

    p = Product.objects.filter(pk=produk_id).first()
    return {"nama": p.name, "toko_id": p.seller_id} if p else None


def pernah_membeli(user, produk_id):
    """True bila user punya pesanan SELESAI yang berisi produk tersebut."""
    if STUB_PEMBELIAN:
        return True
    from apps.checkout.models import OrderItem  # sesuaikan

    return OrderItem.objects.filter(
        order__buyer=user, order__status="selesai", product_id=produk_id
    ).exists()

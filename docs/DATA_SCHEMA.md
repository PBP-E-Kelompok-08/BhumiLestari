# Standar Data Produk BhumiLestari

Status dokumen: **Rancangan v1.0 untuk disepakati kelompok**

Dokumen ini menetapkan bentuk data produk, nilai yang diperbolehkan, dan hubungan data katalog dengan mock API verifikasi. Seluruh contoh perusahaan, hasil pengujian, dan produk dalam tahap pengembangan merupakan data sintetis.

## 1. Hasil sinkronisasi dua versi lama

| Data lama | Struktur final | Keputusan |
|---|---|---|
| `pk` atau `id` sertifikasi | `verification.verification_id` | Dipertahankan sebagai ID hasil verifikasi, bukan ID produk. |
| `product_id` | `product_id` | Dipertahankan sebagai penghubung katalog dan verifikasi. |
| `product_name` | `name` | Disederhanakan agar sesuai model `Product`. |
| `certification: true/false` | Diturunkan dari `verification.status` | Tidak disimpan agar tidak bertentangan dengan status. `verified` berarti tersertifikasi aktif. |
| `eco_rating` | `verification.eco_score` | Dipertahankan sebagai field opsional. Hanya boleh diisi jika kelompok mendokumentasikan skala dan rumusnya. |
| `expire_at` | `verification.valid_until` | Dipertahankan dengan nama yang lebih jelas dan format tanggal ISO `YYYY-MM-DD`. |
| `company` | `verification.partner` | Dipertahankan sebagai lembaga/perusahaan yang melakukan verifikasi. |
| `category` | `category` | Dipertahankan untuk katalog dan filter. |
| `tested_at` | `verification.tested_at` | Dipertahankan. |
| `recycled_material_percent` | `verification.recycled_material_percent` | Dipertahankan, boleh `null` jika tidak relevan. |
| `reusable` | `verification.reusable` | Dipertahankan. |
| `summary` | `verification.summary` | Dipertahankan sebagai penjelasan singkat untuk pengguna. |
| `is_mock` | `meta.is_mock` pada respons API | Dipindahkan ke metadata respons; bukan karakteristik produk. |

## 2. Struktur produk kanonis

```json
{
  "product_id": "prd-001",
  "name": "Tas Belanja Katun Pakai Ulang",
  "slug": "tas-belanja-katun-pakai-ulang",
  "category": "daily_supplies",
  "description": "Tas belanja berbahan katun yang dapat digunakan berulang kali.",
  "price": 35000,
  "stock": 40,
  "seller_id": "sel-001",
  "image_path": "products/prd-001.webp",
  "materials": ["katun"],
  "origin": "Bandung, Jawa Barat",
  "eco_features": [
    "reusable",
    "plastic_free_packaging"
  ],
  "verification": {
    "verification_id": "ver-001",
    "status": "verified",
    "partner": {
      "partner_id": "vfp-001",
      "name": "EcoCheck Indonesia"
    },
    "tested_at": "2026-09-01",
    "valid_until": "2027-09-01",
    "recycled_material_percent": 0,
    "reusable": true,
    "eco_score": null,
    "summary": "Dapat digunakan kembali dan dikemas tanpa plastik sekali pakai."
  },
  "is_active": true
}
```

## 3. Arti dan aturan field

| Field | Tipe | Wajib | Aturan |
|---|---|---:|---|
| `product_id` | string | Ya | Unik. Format `prd-NNN`, misalnya `prd-001`. Tidak boleh berubah setelah dipakai oleh modul lain. |
| `name` | string | Ya | Nama katalog, 3-120 karakter. |
| `slug` | string | Ya | Unik, huruf kecil, angka, dan tanda hubung. Contoh `tas-belanja-katun`. |
| `category` | enum | Ya | Harus salah satu kategori pada bagian 4. |
| `description` | string | Ya | Penjelasan produk, disarankan 40-500 karakter. |
| `price` | integer | Ya | Harga rupiah, minimal 0, tanpa `Rp`, titik, atau koma. |
| `stock` | integer | Ya | Bilangan bulat minimal 0. |
| `seller_id` | string | Ya | ID penjual yang benar-benar tersedia pada data `Seller`. Format yang disarankan `sel-NNN`. |
| `image_path` | string | Ya | Path relatif atau URL yang valid. Nama file disarankan mengikuti `product_id`. |
| `materials` | array string | Ya | Minimal satu material; gunakan huruf kecil dan istilah yang konsisten. |
| `origin` | string | Ya | Kota dan provinsi asal produk. |
| `eco_features` | array enum | Ya | Minimal satu nilai dari bagian 5 dan tidak boleh duplikat. |
| `verification` | object/null | Tidak | `null` jika produk belum mempunyai data verifikasi. |
| `verification.verification_id` | string | Ya* | Unik untuk setiap rekaman verifikasi. Format `ver-NNN`. |
| `verification.status` | enum | Ya* | Harus salah satu status pada bagian 6. |
| `verification.partner` | object | Tidak | Lembaga/perusahaan verifikator; boleh `null` ketika status `pending`. |
| `verification.tested_at` | date/null | Tidak | Format ISO `YYYY-MM-DD`. |
| `verification.valid_until` | date/null | Tidak | Harus sesudah `tested_at`. Produk menjadi `expired` jika tanggal ini terlewati. |
| `verification.recycled_material_percent` | integer/null | Tidak | Rentang 0-100. Gunakan `null` jika kriteria tidak relevan atau belum diuji. |
| `verification.reusable` | boolean/null | Tidak | `true`, `false`, atau `null` jika belum dinilai. |
| `verification.eco_score` | number/null | Tidak | Rentang yang disarankan 0-10. Jangan diisi sebelum rumus dan kriterianya disepakati. |
| `verification.summary` | string/null | Tidak | Ringkasan hasil verifikasi yang dapat dipahami pembeli. |
| `is_active` | boolean | Ya | `true` jika produk boleh ditampilkan dan dibeli. |

`*` Wajib hanya ketika objek `verification` tersedia.

## 4. Kategori produk

| Nilai | Label tampilan | Contoh |
|---|---|---|
| `clothing` | Pakaian | Kaos katun organik, jaket hasil upcycle |
| `daily_supplies` | Perlengkapan sehari-hari | Tas belanja, botol minum, sikat bambu |
| `home_kitchen` | Home & Kitchen | Wadah makanan, peralatan dapur, dekorasi rumah |
| `furniture` | Furniture | Meja kayu daur ulang, kursi rotan |
| `beauty_care` | Beauty & Care | Sabun batang, sampo isi ulang, skincare |

Untuk 50 data awal, distribusi yang disarankan adalah 10 produk per kategori.

## 5. Nilai `eco_features`

| Nilai | Makna |
|---|---|
| `reusable` | Produk dirancang untuk digunakan berulang kali. |
| `refillable` | Wadah atau produk dapat diisi ulang. |
| `recycled_material` | Mengandung material hasil daur ulang. |
| `biodegradable` | Material dapat terurai secara biologis dalam kondisi yang sesuai. |
| `compostable` | Material dapat menjadi kompos dalam kondisi yang ditentukan. |
| `plastic_free_packaging` | Kemasan tidak memakai plastik sekali pakai. |
| `locally_sourced` | Material utama diperoleh dari sumber lokal. |
| `organic_material` | Menggunakan material organik sesuai informasi pemasok/verifikator. |
| `energy_efficient` | Produk membantu mengurangi penggunaan energi. |
| `water_saving` | Produk membantu mengurangi penggunaan air. |

`eco_features` adalah tag yang dapat dipakai untuk filter. Klaim yang membutuhkan pengujian harus didukung oleh data `verification`; jangan menyatakan klaim sintetis sebagai sertifikasi nyata.

## 6. Status verifikasi

| Nilai | Makna | Perilaku tampilan |
|---|---|---|
| `pending` | Belum selesai diperiksa | Tampilkan “Menunggu verifikasi”. |
| `verified` | Lolos verifikasi dan masih berlaku | Tampilkan badge “Terverifikasi”. |
| `rejected` | Tidak memenuhi kriteria | Jangan tampilkan sebagai produk terverifikasi. |
| `expired` | Pernah lolos tetapi masa berlaku habis | Tampilkan “Verifikasi kedaluwarsa”. |

Boolean lama `certification` tidak perlu disimpan. Jika endpoint lama masih memerlukannya untuk kompatibilitas, nilainya dapat dihitung dengan:

```text
certification = verification.status == "verified"
```

## 7. Bentuk respons mock API

Respons daftar:

```json
{
  "meta": {
    "is_mock": true,
    "count": 1
  },
  "data": [
    { "product_id": "prd-001", "name": "Tas Belanja Katun Pakai Ulang" }
  ]
}
```

Respons detail mengembalikan satu objek produk pada `data`. Respons tidak ditemukan menggunakan HTTP `404`:

```json
{
  "meta": { "is_mock": true },
  "error": {
    "code": "PRODUCT_NOT_FOUND",
    "message": "Produk tidak ditemukan"
  }
}
```

Endpoint awal yang disarankan:

```text
GET /api/products
GET /api/products/:product_id
GET /api/products?category=furniture
GET /api/products?eco_feature=reusable
GET /api/products?verification_status=verified
```

## 8. Penerapan pada Django

Pada database, data sebaiknya dinormalisasi menjadi model terpisah:

```text
Seller 1 ─── * Product * ─── 1 Category
                    │
                    └── 0..1 ProductVerification * ─── 1 VerificationPartner
```

- `Product` adalah data utama yang dihitung untuk syarat minimal 50 data.
- `ProductVerification` adalah data pendamping yang terhubung melalui `product_id` atau foreign key.
- `certification` tidak menjadi field database karena dapat diturunkan dari `status`.
- `eco_score` bersifat nullable sampai kelompok memiliki metode penilaian yang konsisten.
- `created_at` dan `updated_at` sebaiknya dibuat otomatis oleh Django dan tidak wajib ada pada dataset sumber.
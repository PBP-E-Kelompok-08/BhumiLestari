# Project Kelompok 8 - PBP E
## BhumiLestari
| Nama | NPM | Peran |
| --- | --- | --- |
| Alfarrel Ersya Balawa | 2506656406 | Mock API, Modul Chat |
| Athifah Mufidah | 2506612045 | UI/UX, Modul Keranjang |
| Nurfadhil Kurniawan | 2506540765 | UI/UX, Modul User |
| Regina Gunadi | 2506542852 | UI/UX, Modul Produk |
| Sultan Noor Dafiq | 2506600713 | Mock API, Modul Ulasan Toko |

## Deskripsi Project
<div align = “justify>
Marketplace yang menjual berbagai macam produk eco-friendly (pakaian, perlengkapan sehari-hari, home & kitchen supplies, furniture, beauty & care) dari penjual yang telah terverifikasi.
</div>

## Target Pengguna
<div align = “justify>
Semua orang yang peduli terkait masalah lingkungan dan ingin berusaha mengurangi dampaknya dengan menggunakan produk eco-friendly. 
</div>

## Fokus Masalah
<div align = “justify>
Akses terhadap produk eco-friendly di Indonesia masih cukup terbatas karena belum adanya marketplace yang terintegrasi. Untuk meningkatkan kesadaran dan kemudahan pembelian, kami berusaha untuk menyediakan platform marketplace produk eco-friendly (BhumiLestari) dari penjual Indonesia yang terverifikasi ramah lingkungan dan dengan harga yang terjangkau.
</div>

## Link Figma
https://www.figma.com/design/JG0Xg7sLjXzbTzazoMqXJY/Project-E08?node-id=1-4&t=Vr0Q4jTZKSs9HeeM-0

## Daftar Modul
| Nomor | Modul | Fungsi | Pemilik |
| --- | --- | --- | --- |
| 1. | User | Laman Profile, Login/Sign Up Pembeli/Penjual | Nurfadhil Kurniawan |
| 2. | Produk | Laman Katalog Produk | Regina Gunadi |
| 3. | Chat | Laman Chat Penjual/Pembeli | Alfarrel Ersya Balawa |
| 4. | Ulasan Toko | Laman Ulasan + Rating Toko | Sultan Noor Dafiq |
| 5. | Keranjang | Laman Keranjang & Checkout | Athifah Mufidah |

## CRUD Tiap Modul
| Modul | Create | Read | Update | Delete|
| --- | --- | --- | --- | --- |
| User | (Seller/Buyer) Sign Up membuat user baru | Melihat profil diri sendiri / user lain | Mengupdate profil diri sendiri | Menghapus akun |
| Produk | (Seller) Membuat produk | Melihat produk | (Seller) Mengedit detail produk | (Seller) Menghapus produk |
| Chat | Membuat session chat baru antara buyer dan seller | Melihat isi chat dan list chat session | Mengupdate isi chat ketika chat baru terkirim | Menghapus chat yang sudah dikirim |
| Ulasan Toko | (Buyer) Membuat ulasan untuk produk yang pernah dibeli. (Seller) Membalas ulasan (pesan singkat) & melaporkan ulasan | (Buyer) Melihat ulasan toko (filter bintang/foto/produk, urutan) dan "Ulasan Saya". (Seller) Melihat ulasan produk di tokonya (filter belum dibalas) | (Buyer) Mengubah ulasan < 7 hari sejak diposting. (Seller) Mengubah balasan < 1 hari sejak balasan diposting | (Buyer) Menghapus ulasannya. (Seller) Menghapus balasannya |
| Keranjang | Menambah barang ke keranjang | Melihat keranjangnya sendiri | Mengupdate jumlah produk di keranjang | Menghapus produk dari keranjang |

## Public API/Mock API
| Nomor | API | Link |
| --- | --- | --- |
| 1. | Mock API data hasil uji produk eco-friendly tiap company partner| <a href="https://drive.google.com/drive/u/1/folders/1sHDq1ZUiYRcyWkg-OhxK9_KpdaMj3ptn"> Google Drive </a>
| 2. | Open Router API untuk chatbot| <a href="https://openrouter.ai/"> OpenRouter </a>|

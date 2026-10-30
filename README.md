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
| 3. | Cloudinary| <a href="https://cloudinary.com/"> Cloudinary </a>|

## AI Disclosure
### Alfarrel Ersya Balawa
<div align = "justify">
AI yang digunakan adalah Gemini. Tujuan penggunaannya adalah untuk membantu mengimplementasikan struktur modul Chat (buyer chat, seller chat, AI chat, broadcast channel, rating chat session, dan report session). Selain itu, AI juga digunakan sebagai rekan diskusi dan debugging dalam menyusun interface, menyusun layout interface pada mobile view, serta membantu penyusunan unit testing.

Strategi prompt yang digunakan adalah dengan tidak langsung mengcopy paste hasil dari AI sehingga kode yang diberikan oleh AI dapat dipelajari secara efektif, dan ditinjau secara detail. Strategi ini saya terapkan pada kode yang menurut saya tidak umum dan ilmunya cukup bernilai untuk menghabiskan waktu mengetik secara manual, sehingga ada beberapa bagian yang tidak menggunakan strategi tersebut.

https://share.gemini.google/UbXVTgv68vdl
</div>

### Athifah Mufidah

### Nurfadhil Kurniawan
<div align = "justify">
Saya menggunakan AI Claude (Free Plan) untuk membantu saya memahami modul Users yang saya kerjakan. Setelah modul ini selesai, saya kembali mengunggah source code modul tersebut dalam bentuk ZIP ke Claude untuk membantu saya mengidentifikasi dan meningkatkan aspek keamanan pada kode yang sudah saya buat.

Dalam prosesnya, saya tetap berusaha mengimplementasikan setiap perbaikan secara mandiri terlebih dahulu. Jika mengalami kesulitan, saya akan meminta Claude memberikan petunjuk (hint) untuk membantu saya menemukan solusinya. Namun, jika saya benar-benar tidak menemukan jalan keluar, barulah saya meminta Claude memberikan contoh implementasi yang benar berdasarkan kode terakhir yang telah saya buat.

Perlu digarisbawahi bahwa AI hanya berperan sebagai alat bantu dalam proses belajar dan pengembangan. Seluruh keputusan terkait solusi yang digunakan dan implementasi akhir tetap berada di tangan saya sepenuhnya.
Berikut adalah beberapa link Claude yg saya gunakan:
<ul>
<li>https://claude.ai/share/e22275f6-35e4-477b-8004-6de52e3428c1</li>
<li>https://claude.ai/share/6df6be04-f70c-4378-beca-70341a82ea97</li>
</ul>
</div>

### Regina Gunadi
<div align = "justify">
AI yang digunakan adalah Claude (free plan) dan AI Overview di Google. Tujuan penggunaannya adalah untuk mempersingkat waktu pembuatan template HTML dan CSS, membantu menjelaskan beberapa hal yang saya tidak pahami dan bingung, serta sebagai teman debugging dan diskusi penerapan best practices. Selain itu, saya juga gunakan untuk membantu memahami kodingan teman yang ditambahkan di beberapa files bagian saya. Strategi prompt yang digunakan adalah berusaha menjelaskan kondisi yang terjadi, lalu ide saya untuk menyelesaikannya dan meminta verifikasi apakah keputusan tersebut sesuai. Untuk beberapa kasus, saya tidak mendapat ide sehingga saya bertanya langsung dan selalu berusaha untuk meminta untuk dijelaskan. Saat mendapat jawaban dari AI, saya membaca dan melakukan filtering per bagian sebelum diimplementasikan ke dalam kode. 
Berikut adalah beberapa link chatnya: 
<ul>
<li>https://claude.ai/share/df222b12-1a39-4bf3-848c-a909ff8204ee</li>
<li>https://claude.ai/share/568656c7-a1ce-4928-850f-ed3ee4997029</li>
<li>https://claude.ai/share/2c2f96fe-01d3-4a0b-977c-eff8a25a73fb</li>
</ul>
</div>

### Sultan Noor Dafiq
<div align = "justify">
AI yang saya gunakan adalah OpenAI Codex. Saya menggunakannya sebagai rekan diskusi dan pendamping teknis selama mengembangkan Mock API, modul Ulasan Toko, integrasi antarmodul, deployment ke PWS, dan pengujian aplikasi. AI membantu saya menelusuri alur kode, mencari penyebab bug, membandingkan beberapa alternatif solusi, memeriksa konfigurasi keamanan, serta menyusun dan menjalankan unit test. Saya juga menggunakannya untuk memeriksa kesesuaian data Mock API dengan repository utama dan memahami alur checkout lintas toko karena alur tersebut berhubungan langsung dengan hak pembeli untuk memberikan ulasan.

Strategi prompt yang saya gunakan adalah memberikan konteks masalah, output terminal, hasil pengujian, dan tujuan yang ingin dicapai secara bertahap. Saya tidak langsung menyalin jawaban AI, tetapi membaca diff dan menelusuri hubungan antara model, view, service, template, serta test terlebih dahulu. Ketika belum memahami suatu bagian, saya meminta penjelasan mengenai alasan dan dampak dari perubahan tersebut. Saya juga menjalankan perintahnya sendiri, membaca error yang muncul, dan memperbaiki solusi bersama AI sampai hasilnya dapat saya jelaskan kembali.

Setiap solusi saya verifikasi melalui unit test, Django system check, pemeriksaan migrasi, dan pengujian langsung pada deployment PWS. Sepanjang proses tersebut, saya bersungguh-sungguh memahami autentikasi API, pengelolaan secret melalui environment variable, pemisahan pesanan berdasarkan toko, pembatasan ulasan berdasarkan transaksi yang selesai, agregasi statistik menggunakan Django ORM, migrasi data, serta pengelolaan static dan media files di lingkungan produksi. Bagi saya, AI berperan sebagai pendamping belajar dan alat untuk memperluas sudut pandang, bukan sebagai pengganti proses berpikir. Keputusan mengenai implementasi, merge, dan deployment tetap saya ambil setelah memahami serta menguji dampaknya terhadap modul saya maupun modul anggota lain.

Berikut adalah link percakapan AI yang mendokumentasikan proses diskusi, implementasi, debugging, pengujian, dan deployment yang saya lakukan:
<ul>
<li>https://chatgpt.com/s/cx_6ae4a43362888191ae7bde88fbadb103</li>
</ul>
</div>

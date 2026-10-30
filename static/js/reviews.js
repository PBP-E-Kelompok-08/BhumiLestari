(function () {
  "use strict";

  const root = document.getElementById("rv-root");
  if (!root) return;

  const D = root.dataset;
  const mode = D.mode; // "toko" | "penjual" | "saya"
  const csrf = document.getElementById("rv-csrf").value;

  const el = (id) => document.getElementById(id);
  const list = el("rv-list");
  const stLoading = el("rv-loading");
  const stError = el("rv-error");
  const stKosong = el("rv-kosong");
  const btnLagi = el("rv-lagi");
  const skorEl = el("rv-skor");
  const distEl = el("rv-dists");
  const filter = el("rv-filter");
  const formTulis = el("rv-form-tulis");
  const toast = el("rv-toast");
  const dialog = el("rv-dialog");
  const dialogForm = el("rv-dialog-form");
  const lightbox = el("rv-lightbox");
  const lightboxImg = el("rv-lightbox-img");
  const btnTutupLightbox = el("rv-lightbox-tutup");

  const state = { page: 1, items: new Map(), controller: null };

  // ---------- util ----------
  function esc(teks) {
    const peta = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };
    return String(teks ?? "").replace(/[&<>"']/g, (c) => peta[c]);
  }

  function urlDari(nama, id) {
    // data-url-* berisi pola ".../0/...": ganti segmen 0 dengan id
    return D[nama].replace("/0/", "/" + id + "/");
  }

  /** Baris 5 ikon pohon; yang terisi sebanyak n. */
  function pohon(n) {
    let html = "";
    for (let i = 1; i <= 5; i++) {
      html += `<svg class="rv-pohon${i <= n ? "" : " kosong"}" aria-hidden="true"><use href="#rv-pohon"/></svg>`;
    }
    return `<div class="rv-pohon-baris" role="img" aria-label="Rating ${n} dari 5">${html}</div>`;
  }

  function tampilToast(pesan, bahaya = false) {
    toast.textContent = pesan;
    toast.classList.toggle("rv-toast-error", bahaya);
    toast.hidden = false;
    clearTimeout(tampilToast.t);
    tampilToast.t = setTimeout(() => {
      toast.hidden = true;
      toast.classList.remove("rv-toast-error");
    }, 3500);
  }

  async function kirim(url, body) {
    const res = await fetch(url, {
      method: "POST",
      body,
      credentials: "same-origin",
      headers: { "X-CSRFToken": csrf, Accept: "application/json" },
    });
    let data = {};
    try {
      data = await res.json();
    } catch (_) {
      /* respons bukan JSON */
    }
    if (!res.ok || data.ok === false) {
      const err = new Error(data.error || "Terjadi kesalahan (" + res.status + ").");
      err.status = res.status;
      throw err;
    }
    return data;
  }

  // ---------- status tampilan ----------
  function setStatus({ loading = false, error = false, kosong = false }) {
    stLoading.hidden = !loading;
    stError.hidden = !error;
    stKosong.hidden = !kosong;
  }

  function filterAktif() {
    return filter && Array.from(bacaFilter().keys()).some((k) => k !== "urut");
  }

  function perbaruiKosong() {
    const kosong = list.children.length === 0 && btnLagi.hidden;
    if (kosong) {
      stKosong.textContent = filterAktif()
        ? "Tidak ada ulasan yang cocok dengan filter."
        : mode === "saya"
        ? "Anda belum menulis ulasan."
        : "Belum ada ulasan.";
    }
    stKosong.hidden = !kosong;
  }

  // ---------- ringkasan rating (kotak skor + bar distribusi) ----------
  function angka(rata) {
    return Number(rata).toFixed(1); // mengikuti desain Figma: 4.8
  }

  /** r = ringkasan toko, rp = ringkasan produk (bila filter produk aktif). */
  function renderRingkasan(r, rp) {
    if (!skorEl || !r) return;
    const pakai = rp || r;
    const keterangan = rp
      ? `${rp.total} dari ${r.total} ulasan`
      : `${r.total} ulasan`;

    if (!pakai.total) {
      skorEl.innerHTML = `<span class="rv-skor-angka">-</span>${pohon(0)}<small>${esc(keterangan)}</small>`;
    } else {
      skorEl.innerHTML = `
        <span class="rv-skor-angka">${angka(pakai.rata_rata)}</span>
        ${pohon(Math.round(pakai.rata_rata))}
        <small>${esc(keterangan)}</small>`;
    }

    distEl.innerHTML = [5, 4, 3, 2, 1]
      .map((n) => {
        const jml = pakai.distribusi[n] || 0;
        const persen = pakai.total ? Math.round((jml / pakai.total) * 1000) / 10 : 0;
        return `
        <div class="rv-dist">
          <svg class="rv-pohon" aria-hidden="true"><use href="#rv-pohon"/></svg>
          <b>${n}</b>
          <span class="rv-bar" role="img" aria-label="${jml} ulasan rating ${n}"><i style="width:${persen}%"></i></span>
          <span class="rv-dist-jml">${jml}</span>
        </div>`;
      })
      .join("");
  }

  /** Ambil ulang hanya ringkasan (setelah tambah/edit/hapus) tanpa memuat ulang daftar. */
  async function segarkanRingkasan() {
    if (!skorEl) return;
    try {
      const params = bacaFilter();
      params.set("page", 1);
      const res = await fetch(D.urlData + "?" + params.toString(), {
        credentials: "same-origin",
        headers: { Accept: "application/json" },
      });
      const data = await res.json();
      if (res.ok && data.ok) renderRingkasan(data.ringkasan, data.ringkasan_produk);
    } catch (_) {
      /* ringkasan akan diperbarui pada pemuatan berikutnya */
    }
  }

  // ---------- item ulasan ----------
  function badgeProduk(p) {
    const kelas = p.status ? "rv-st-" + esc(p.status) : "rv-st-hilang";
    const teks = p.status ? "Produk " + p.status_display.toLowerCase() : p.status_display;
    return `<span class="rv-badge ${kelas}">${esc(teks)}</span>`;
  }

  function renderBalasan(u) {
    if (!u.balasan) return "";
    const b = u.balasan;
    const aksi = b.milik_saya
      ? `<div class="rv-aksi">
          ${b.bisa_diedit ? '<button type="button" class="rv-link" data-aksi="balas-edit">Edit balasan</button>' : ""}
          <button type="button" class="rv-link rv-link-bahaya" data-aksi="balas-hapus">Hapus balasan</button>
        </div>`
      : "";
    return `
      <div class="rv-balasan">
        <strong>Balasan penjual</strong> <small>${esc(b.tanggal)}</small>
        <p>${esc(b.pesan)}</p>
        ${aksi}
      </div>`;
  }

  function renderFoto(u) {
    if (u.foto.length) {
      return `<div class="rv-foto">${u.foto
        .map(
          (src) =>
            `<button type="button" class="rv-foto-btn" data-foto-src="${esc(src)}" aria-label="Perbesar foto ulasan"><img src="${esc(src)}" alt="Foto ulasan" loading="lazy"></button>`
        )
        .join("")}</div>`;
    }
    if (u.foto_terkunci) {
      return `<p class="rv-kunci">${u.jumlah_foto} foto disembunyikan. <a href="${esc(D.urlLogin)}">Login</a> untuk melihatnya.</p>`;
    }
    return "";
  }

  function renderUlasan(u) {
    const tokoLink =
      mode === "saya"
        ? `<a class="rv-toko" href="${esc(urlDari("urlToko", u.toko.id))}">${esc(u.toko.nama)}</a>`
        : "";
    const aksi = [];
    if (u.bisa_diedit) aksi.push('<button type="button" class="rv-link" data-aksi="edit">Edit</button>');
    if (u.bisa_dihapus) aksi.push('<button type="button" class="rv-link rv-link-bahaya" data-aksi="hapus">Hapus</button>');
    if (u.bisa_dibalas) aksi.push('<button type="button" class="rv-link" data-aksi="balas">Balas</button>');
    if (u.bisa_dilaporkan) aksi.push('<button type="button" class="rv-link rv-link-bahaya" data-aksi="laporkan">Laporkan</button>');

    const inisial = (u.pembeli || "?").trim().charAt(0);
    return `
      <article class="rv-item" data-id="${u.id}">
        <div class="rv-avatar rv-av-${u.id % 4}" aria-hidden="true">${esc(inisial)}</div>
        <div class="rv-isi">
          <header class="rv-item-head">
            <strong class="rv-pembeli">${esc(u.pembeli)}</strong>
            <time class="rv-waktu">${esc(u.waktu)}${u.diedit ? " (diedit)" : ""}</time>
          </header>
          ${pohon(u.rating)}
          <p class="rv-meta">
            ${tokoLink}
            <span class="rv-produk">${esc(u.produk.nama)}</span>
            ${badgeProduk(u.produk)}
            ${u.terverifikasi ? '<span class="rv-badge rv-st-beli">Pembelian terverifikasi</span>' : ""}
          </p>
          ${u.disembunyikan ? '<p class="rv-peringatan">Ulasan ini disembunyikan admin dan tidak tampil ke publik.</p>' : ""}
          ${u.laporan_admin ? `
            <div class="rv-laporan-admin">
              <strong>Laporan ${esc(u.laporan_admin.status_display)}</strong>
              <span>oleh ${esc(u.laporan_admin.pelapor)}: ${esc(u.laporan_admin.alasan)}</span>
              ${u.laporan_admin.status === "menunggu" ? `<a href="${esc(D.urlModerasi)}">Tinjau laporan</a>` : ""}
            </div>` : ""}
          ${u.komentar ? `<p class="rv-komentar">${esc(u.komentar)}</p>` : ""}
          ${renderFoto(u)}
          ${renderBalasan(u)}
          ${aksi.length ? `<div class="rv-aksi">${aksi.join("")}</div>` : ""}
        </div>
      </article>`;
  }

  function buatElemen(u) {
    const tmp = document.createElement("div");
    tmp.innerHTML = renderUlasan(u).trim();
    return tmp.firstElementChild;
  }

  function simpanDanTaruh(u, { depan = false, highlight = false } = {}) {
    state.items.set(u.id, u);
    const baru = buatElemen(u);
    if (highlight) baru.classList.add("rv-item-highlight");
    const lama = list.querySelector(`[data-id="${u.id}"]`);
    if (lama) lama.replaceWith(baru);
    else if (depan) list.prepend(baru);
    else list.append(baru);
  }

  // ---------- filter (chip + opsi lanjutan) ----------
  function bacaFilter() {
    const p = new URLSearchParams();
    if (!filter) return p;
    for (const [k, v] of new FormData(filter).entries()) {
      if (v === "" || v == null) continue;
      p.set(k, v === "on" ? "1" : v);
    }
    return p;
  }

  function sinkronChip() {
    if (!filter) return;
    const rating = filter.elements.rating.value;
    const foto = filter.elements.foto.value === "1";
    filter.querySelectorAll(".rv-chip").forEach((c) => {
      let aktif = false;
      if (c.dataset.chip === "semua") aktif = !rating && !foto;
      else if (c.dataset.chip === "foto") aktif = foto;
      else aktif = rating === c.dataset.nilai;
      c.classList.toggle("is-aktif", aktif);
      if (c.dataset.chip !== "semua") c.setAttribute("aria-pressed", aktif ? "true" : "false");
    });
  }

  if (filter) {
    filter.addEventListener("click", (ev) => {
      const chip = ev.target.closest(".rv-chip");
      if (!chip) return;
      const { rating, foto } = filter.elements;
      if (chip.dataset.chip === "semua") {
        rating.value = "";
        foto.value = "";
      } else if (chip.dataset.chip === "foto") {
        foto.value = foto.value === "1" ? "" : "1";
      } else {
        rating.value = rating.value === chip.dataset.nilai ? "" : chip.dataset.nilai;
      }
      sinkronChip();
      muat(true);
    });

    filter.addEventListener("change", (e) => {
      sinkronChip();
      if (formTulis && e.target && e.target.name === "produk") {
        const pSelect = formTulis.querySelector('select[name="produk_id"]');
        if (pSelect && e.target.value) {
          pSelect.value = e.target.value;
        }
      }
      muat(true);
    });

    el("rv-reset").addEventListener("click", () => {
      filter.elements.rating.value = "";
      filter.elements.foto.value = "";
      filter.elements.produk.value = "";
      filter.elements.urut.value = "terbaru";
      filter.elements.terverifikasi.checked = false;
      if (filter.elements.belum_dibalas) filter.elements.belum_dibalas.checked = false;
      sinkronChip();
      muat(true);
    });

    sinkronChip();
  }

  // ---------- muat data ----------
  async function muat(reset) {
    if (state.controller) state.controller.abort();
    state.controller = new AbortController();

    if (reset) {
      state.page = 1;
      state.items.clear();
      list.innerHTML = "";
      btnLagi.hidden = true;
    } else {
      state.page += 1;
    }
    setStatus({ loading: true });

    const params = bacaFilter();
    params.set("page", state.page);

    try {
      const res = await fetch(D.urlData + "?" + params.toString(), {
        credentials: "same-origin",
        headers: { Accept: "application/json" },
        signal: state.controller.signal,
      });
      const data = await res.json();
      if (!res.ok || !data.ok) throw new Error(data.error || "HTTP " + res.status);

      data.ulasan.forEach((u) => simpanDanTaruh(u));
      renderRingkasan(data.ringkasan, data.ringkasan_produk);
      btnLagi.hidden = !data.ada_berikutnya;
      setStatus({});
      perbaruiKosong();
    } catch (err) {
      if (err.name === "AbortError") return;
      console.error("Gagal memuat ulasan:", err);
      if (!reset) state.page -= 1;
      setStatus({ error: true });
    }
  }

  // ---------- dialog (edit, balas, laporkan, hapus) ----------
  let aksiDialog = null;

  function bukaDialog({ judul, tpl, pesan, tombol = "Simpan", bahaya = false, isi, kirimKe }) {
    el("rv-dialog-judul").textContent = judul;
    const wadah = el("rv-dialog-isi");
    wadah.innerHTML = "";
    if (tpl) {
      wadah.append(document.getElementById(tpl).content.cloneNode(true));
    } else {
      const p = document.createElement("p");
      p.textContent = pesan;
      wadah.append(p);
    }
    if (isi) isi(dialogForm);

    const btn = el("rv-dialog-kirim");
    btn.textContent = tombol;
    btn.classList.toggle("rv-btn-bahaya", bahaya);
    btn.classList.toggle("rv-btn-utama", !bahaya);
    setErrorDialog("");
    aksiDialog = kirimKe;
    dialog.showModal();
    const pertama = dialogForm.querySelector("textarea, input, select");
    if (pertama) pertama.focus();
  }

  function setErrorDialog(pesan) {
    const e = el("rv-dialog-error");
    e.textContent = pesan;
    e.hidden = !pesan;
  }

  el("rv-dialog-batal").addEventListener("click", () => dialog.close());

  dialogForm.addEventListener("submit", async (ev) => {
    ev.preventDefault();
    if (!aksiDialog) return;
    const btn = el("rv-dialog-kirim");
    btn.disabled = true;
    setErrorDialog("");
    try {
      await aksiDialog(new FormData(dialogForm));
      dialog.close();
    } catch (err) {
      setErrorDialog(err.message);
    } finally {
      btn.disabled = false;
    }
  });

  // ---------- aksi per ulasan ----------
  function setelahUbah(data) {
    if (data.ulasan) simpanDanTaruh(data.ulasan, { highlight: true });
    segarkanRingkasan();
  }

  list.addEventListener("click", (ev) => {
    // Lightbox Foto: Perbesar gambar saat diklik dengan backdrop blur
    const fotoBtn = ev.target.closest("[data-foto-src]");
    if (fotoBtn && lightbox && lightboxImg) {
      lightboxImg.src = fotoBtn.dataset.fotoSrc;
      lightbox.showModal();
      return;
    }

    const tombol = ev.target.closest("[data-aksi]");
    if (!tombol) return;
    const item = tombol.closest("[data-id]");
    const id = Number(item.dataset.id);
    const u = state.items.get(id);
    if (!u) return;

    switch (tombol.dataset.aksi) {
      case "edit":
        bukaDialog({
          judul: "Edit Ulasan",
          tpl: "tpl-edit",
          isi: (f) => {
            const radio = f.querySelector(`input[name="rating"][value="${u.rating}"]`);
            if (radio) radio.checked = true;
            f.querySelector('[name="komentar"]').value = u.komentar;
          },
          kirimKe: async (fd) => setelahUbah(await kirim(urlDari("urlEdit", id), fd)),
        });
        break;

      case "hapus":
        bukaDialog({
          judul: "Hapus ulasan?",
          pesan: "Ulasan ini akan dihapus permanen dan rating toko dihitung ulang.",
          tombol: "Ya, Hapus",
          bahaya: true,
          kirimKe: async (fd) => {
            // Optimistic UI: Segera tutup dialog dan sembunyikan item dengan animasi instan
            dialog.close();
            item.classList.add("rv-item-optimistic-delete");
            tampilToast("Menghapus ulasan...");

            try {
              await kirim(urlDari("urlHapus", id), fd);
              state.items.delete(id);
              item.remove();
              segarkanRingkasan();
              perbaruiKosong();
              tampilToast("Ulasan berhasil dihapus.");
            } catch (err) {
              // Rollback visual jika server mengembalikan error atau jaringan putus
              item.classList.remove("rv-item-optimistic-delete");
              tampilToast(err.message || "Gagal menghapus ulasan.", true);
            }
          },
        });
        break;

      case "balas":
        bukaDialog({
          judul: "Balas Ulasan",
          tpl: "tpl-balas",
          tombol: "Kirim Balasan",
          kirimKe: async (fd) => {
            setelahUbah(await kirim(urlDari("urlBalas", id), fd));
            tampilToast("Balasan terkirim.");
          },
        });
        break;

      case "balas-edit":
        bukaDialog({
          judul: "Edit Balasan",
          tpl: "tpl-balas",
          isi: (f) => (f.querySelector('[name="pesan"]').value = u.balasan.pesan),
          kirimKe: async (fd) => setelahUbah(await kirim(urlDari("urlBalasEdit", id), fd)),
        });
        break;

      case "balas-hapus":
        bukaDialog({
          judul: "Hapus balasan?",
          pesan: "Balasan Anda akan dihapus. Anda bisa membalas lagi setelahnya.",
          tombol: "Ya, Hapus",
          bahaya: true,
          kirimKe: async (fd) => {
            // Optimistic UI: Segera tutup dialog dan hilangkan tampilan balasan
            dialog.close();
            const balasanLama = u.balasan;
            u.balasan = null;
            u.bisa_dibalas = true;
            simpanDanTaruh(u, { highlight: true });
            tampilToast("Menghapus balasan...");

            try {
              await kirim(urlDari("urlBalasHapus", id), fd);
              tampilToast("Balasan berhasil dihapus.");
            } catch (err) {
              // Rollback jika gagal
              u.balasan = balasanLama;
              u.bisa_dibalas = false;
              simpanDanTaruh(u);
              tampilToast(err.message || "Gagal menghapus balasan.", true);
            }
          },
        });
        break;

      case "laporkan":
        bukaDialog({
          judul: "Laporkan Ulasan",
          tpl: "tpl-laporan",
          tombol: "Kirim Laporan",
          bahaya: true,
          kirimKe: async (fd) => {
            const data = await kirim(urlDari("urlLaporkan", id), fd);
            u.bisa_dilaporkan = false;
            simpanDanTaruh(u);
            tampilToast(data.pesan || "Laporan terkirim.");
          },
        });
        break;
    }
  });

  // ---------- tulis ulasan baru ----------
  if (formTulis) {
    const errTulis = el("rv-tulis-error");
    formTulis.addEventListener("submit", async (ev) => {
      ev.preventDefault();
      errTulis.hidden = true;
      const btn = formTulis.querySelector('[type="submit"]');
      btn.disabled = true;
      try {
        const data = await kirim(D.urlTambah, new FormData(formTulis));
        simpanDanTaruh(data.ulasan, { depan: true, highlight: true });
        segarkanRingkasan();
        stKosong.hidden = true;

        // produk yang baru diulas tidak bisa diulas lagi
        const pilih = formTulis.querySelector('select[name="produk_id"]');
        const opsi = pilih.querySelector(`option[value="${data.ulasan.produk.id}"]`);
        if (opsi) opsi.remove();
        formTulis.reset();
        if (pilih.options.length <= 1) formTulis.hidden = true;
        if (document.activeElement) document.activeElement.blur();
        tampilToast("Ulasan terkirim. Terima kasih!");
      } catch (err) {
        errTulis.textContent = err.message;
        errTulis.hidden = false;
      } finally {
        btn.disabled = false;
      }
    });
  }

  if (lightbox) {
    lightbox.addEventListener("click", (e) => {
      // Tutup jika klik backdrop atau tombol tutup
      if (e.target === lightbox || (btnTutupLightbox && e.target === btnTutupLightbox)) {
        lightbox.close();
      }
    });
  }

  btnLagi.addEventListener("click", () => muat(false));
  el("rv-coba-lagi").addEventListener("click", () => muat(state.items.size === 0));

  muat(true);
})();

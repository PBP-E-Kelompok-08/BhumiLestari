const input = document.getElementById("search-input");
const form = document.getElementById("search-form");
const grid = document.getElementById("product-grid");
const loadingState = document.getElementById("loading");
const errorState = document.getElementById("error");
const emptyState = document.getElementById("empty");
const emptyMessage = document.getElementById("empty-message");

const deletePopover = document.getElementById("delete-popover");
const deleteForm = document.getElementById("delete-form");
const deleteName = document.getElementById("delete-product-name");

const apiUrl = "/api/products/";

function escapeHtml(text) {
  const map = {
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  };

  return String(text ?? "").replace(/[&<>"']/g, function (char) {
    return map[char];
  });
}

function formatRupiah(number) {
  return number.toLocaleString("id-ID");
}

function showSection({ loading = false, error = false, empty = false, products = false }) {
  loadingState.classList.toggle("hide", !loading);
  errorState.classList.toggle("hide", !error);
  emptyState.classList.toggle("hide", !empty);
  grid.classList.toggle("hide", !products);
}

function renderActions(product, role, loginUrl) {
  const deleteButton = `
    <button type="button"
            class="dash-btn dash-btn-delete"
            data-delete-url="${escapeHtml(product.delete_url)}"
            data-name="${escapeHtml(product.name)}">
      Hapus Item
    </button>`;

  const editLink = `
    <a href="${escapeHtml(product.edit_url)}" class="dash-btn dash-btn-edit">Edit Item</a>`;

  const cartButton = `
    <button type="button" class="dash-btn dash-btn-cart"
      data-product-id="${escapeHtml(product.id)}">+ Tambah ke Keranjang</button>`;

  const loginLink = `
    <a href="${escapeHtml(loginUrl)}" class="dash-btn dash-btn-cart">+ Tambah ke Keranjang</a>`;

  const actionsByRole = {
    admin: deleteButton,
    seller: editLink + deleteButton,
    buyer: cartButton,
    guest: loginLink,
  };

  return actionsByRole[role] ?? "";
}

function renderStatus(product, role) {
  if (role !== "seller" && role !== "admin") return "";

  const badge = `
    <span class="status-badge status-${escapeHtml(product.status)}">
      ${escapeHtml(product.status_display)}
    </span>`;

  const note =
    product.status === "rejected" && product.verification_summary
      ? `<p class="status-note">${escapeHtml(product.verification_summary)}</p>`
      : "";

  return badge + note;
}

function renderCard(product, role, loginUrl) {
  const image = product.image
    ? `<img src="${escapeHtml(product.image)}" alt="${escapeHtml(product.name)}">`
    : "";

  const discount = product.discount
    ? `<span class="dash-badge">Diskon: ${product.discount}%</span>`
    : "";

  return `
    <article class="dash-card">
      <div class="dash-card-img">${image}</div>
      <h2 class="dash-card-name">${escapeHtml(product.name)}</h2>
      <div class="dash-card-price">
        <span>Rp. ${formatRupiah(product.final_price)}</span>
        ${discount}
      </div>
      ${renderStatus(product, role)}
      <div class="dash-card-actions">
        <a href="#" class="dash-btn dash-btn-review">Lihat Review</a>
        ${renderActions(product, role, loginUrl)}
      </div>
    </article>`;
}

let controller;

function cari() {
  if (controller) controller.abort();
  controller = new AbortController();

  showSection({ loading: true });

  const url = apiUrl + "?title=" + encodeURIComponent(input.value.trim());

  fetch(url, {
    headers: { Accept: "application/json" },
    signal: controller.signal,
  })
    .then((res) => {
      if (!res.ok) throw new Error("HTTP " + res.status);
      return res.json();
    })
    .then((data) => {
      if (data.products.length === 0) {
        emptyMessage.textContent = data.query
          ? `Tidak ada produk untuk "${data.query}".`
          : "Belum ada produk.";
        showSection({ empty: true });
        return;
      }

      grid.innerHTML = data.products
        .map((product) => renderCard(product, data.role, data.login_url))
        .join("");
      showSection({ products: true });
    })
    .catch((error) => {
      if (error.name === "AbortError") return;
      console.error("Gagal memuat produk:", error);
      showSection({ error: true });
    });
}

let timer;

input.addEventListener("input", () => {
  clearTimeout(timer);
  timer = setTimeout(cari, 300);
});

form.addEventListener("submit", (event) => {
  event.preventDefault();
  clearTimeout(timer);
  cari();
});

grid.addEventListener("click", (event) => {
  const button = event.target.closest("[data-delete-url]");
  if (!button) return;

  deleteForm.action = button.dataset.deleteUrl;
  deleteName.textContent = button.dataset.name;
  deletePopover.showPopover();
});

grid.addEventListener("click", async (event) => {
  const button = event.target.closest("[data-product-id]");
  if (!button) return;

  const originalText = button.textContent;
  button.disabled = true;

  try {
    const csrf = document.querySelector("[name=csrfmiddlewaretoken]").value;
    const res = await fetch(`/cart/add/${button.dataset.productId}/`, {
      method: "POST",
      headers: { "X-CSRFToken": csrf },
    });
    const data = await res.json();
    button.textContent = data.ok ? "✓ Ditambahkan" : (data.error || "Gagal");
  } catch (error) {
    console.error("Gagal menambah ke keranjang:", error);
    button.textContent = "Gagal, coba lagi";
  }

  setTimeout(() => {
    button.textContent = originalText;
    button.disabled = false;
  }, 1500);
});

cari();
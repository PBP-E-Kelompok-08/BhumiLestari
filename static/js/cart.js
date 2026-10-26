(function () {
    var selectAll = document.getElementById('select-all');
    var list = document.querySelector('.cart-list');
    var totalEl = document.getElementById('summary-total');
    var selectCount = document.getElementById('select-count');
    var checkoutCount = document.getElementById('checkout-count');
    var checkoutBtn = document.getElementById('checkout-btn');
    var deleteBtn = document.querySelector('.cart-delete-btn');
    var csrfInput = document.querySelector('[name=csrfmiddlewaretoken]');
    var csrf = csrfInput ? csrfInput.value : '';

    function rupiah(n) {
        return 'Rp. ' + String(n).replace(/\B(?=(\d{3})+(?!\d))/g, '.');
    }

    function setText(el, text) {
        if (el) el.textContent = text;
    }

    function setState(box, all, none) {
        box.checked = all;
        box.indeterminate = !all && !none;
    }

    function post(url, data) {
        return fetch(url, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf },
            body: JSON.stringify(data || {})
        }).then(function (res) {
            return res.json();
        });
    }

    function syncChecks() {
        document.querySelectorAll('.cart-store').forEach(function (store) {
            var boxes = store.querySelectorAll('.item-check');
            var checked = store.querySelectorAll('.item-check:checked').length;
            setState(store.querySelector('.store-check'), checked === boxes.length, checked === 0);
        });
        var all = document.querySelectorAll('.item-check').length;
        var checkedAll = document.querySelectorAll('.item-check:checked').length;
        setState(selectAll, all > 0 && checkedAll === all, checkedAll === 0);
    }

    function recalc() {
        var count = 0;
        var sum = 0;
        document.querySelectorAll('.cart-item').forEach(function (row) {
            if (!row.querySelector('.item-check').checked) return;
            var qty = parseInt(row.querySelector('.qty-value').textContent, 10) || 0;
            count += qty;
            sum += qty * (parseInt(row.dataset.price, 10) || 0);
        });
        setText(totalEl, rupiah(sum));
        setText(checkoutCount, count);
        if (checkoutBtn) checkoutBtn.classList.toggle('is-disabled', count === 0);
    }

    function refresh() {
        syncChecks();
        recalc();
    }

    // Simpan checklist ke database
    function saveSelection() {
        var ids = [];
        document.querySelectorAll('.cart-item').forEach(function (row) {
            if (row.querySelector('.item-check').checked) {
                ids.push(parseInt(row.dataset.itemId, 10));
            }
        });
        post('/cart/select/', { selected_ids: ids }).catch(function (err) {
            console.error('Gagal menyimpan centang:', err);
        });
    }

    function refreshAndSave() {
        refresh();
        saveSelection();
    }

    function showEmptyIfNeeded() {
        if (document.querySelector('.cart-item')) return;
        var card = document.createElement('div');
        card.className = 'cc-card';
        card.innerHTML = '<p>Keranjang kamu masih kosong.</p>';
        list.appendChild(card);
    }

    selectAll.addEventListener('change', function () {
        document.querySelectorAll('.store-check, .item-check').forEach(function (box) {
            box.checked = selectAll.checked;
        });
        refreshAndSave();
    });

    document.querySelectorAll('.cart-store').forEach(function (store) {
        store.querySelector('.store-check').addEventListener('change', function (e) {
            store.querySelectorAll('.item-check').forEach(function (box) {
                box.checked = e.target.checked;
            });
            refreshAndSave();
        });
    });

    document.querySelectorAll('.item-check').forEach(function (box) {
        box.addEventListener('change', refreshAndSave);
    });

    if (checkoutBtn) {
        checkoutBtn.addEventListener('click', function (e) {
            if (checkoutBtn.classList.contains('is-disabled')) e.preventDefault();
        });
    }

    // Pop up konfirmasi
    var modal = document.getElementById('delete-modal');
    var modalText = document.getElementById('delete-modal-text');
    var pendingRows = [];

    function closeModal() {
        modal.hidden = true;
        pendingRows = [];
    }

    function deleteRows(rows) {
        rows.forEach(function (row) {
            var store = row.closest('.cart-store');
            row.remove();
            if (store && !store.querySelector('.cart-item')) store.remove();
        });
        setText(selectCount, document.querySelectorAll('.cart-item').length);
        showEmptyIfNeeded();
        refresh();
    }

    if (deleteBtn && modal) {
        deleteBtn.addEventListener('click', function () {
            var rows = [];
            document.querySelectorAll('.cart-item').forEach(function (row) {
                if (row.querySelector('.item-check').checked) rows.push(row);
            });
            if (rows.length === 0) return;
            pendingRows = rows;
            modalText.textContent = rows.length + ' produk akan dihapus dari keranjang.';
            modal.hidden = false;
        });

        document.getElementById('delete-cancel').addEventListener('click', closeModal);
        document.getElementById('delete-confirm').addEventListener('click', function () {
            var rows = pendingRows;
            var ids = rows.map(function (row) { return parseInt(row.dataset.itemId, 10); });
            closeModal();

            post('/cart/delete/', { ids: ids }).then(function (data) {
                if (data.ok) {
                    deleteRows(rows);
                } else {
                    alert(data.error || 'Gagal menghapus dari keranjang.');
                }
            }).catch(function (err) {
                console.error('Gagal menghapus:', err);
                alert('Terjadi kesalahan. Coba lagi.');
            });
        });
        modal.addEventListener('click', function (e) {
            if (e.target === modal) closeModal();
        });
        document.addEventListener('keydown', function (e) {
            if (e.key === 'Escape' && !modal.hidden) closeModal();
        });
    }

    function updateStepper(row) {
        var qty = parseInt(row.querySelector('.qty-value').textContent, 10) || 1;
        var stock = parseInt(row.dataset.stock, 10);
        row.querySelector('.qty-minus').disabled = qty <= 1;
        row.querySelector('.qty-plus').disabled = !isNaN(stock) && qty >= stock;
    }

    document.querySelectorAll('.cart-item').forEach(function (row) {
        var valueEl = row.querySelector('.qty-value');

        function render(n) {
            valueEl.textContent = n;
            updateStepper(row);
            recalc();
        }

        function setQty(n) {
            var old = parseInt(valueEl.textContent, 10) || 1;
            n = Math.max(1, n);
            if (n === old) return;

            render(n); // tampil dulu, lalu simpan; kalau ditolak server, balik ke angka lama
            post('/cart/update/' + row.dataset.itemId + '/', { quantity: n })
                .then(function (data) {
                    if (!data.ok) {
                        render(old);
                        alert(data.error || 'Gagal mengubah jumlah.');
                    }
                })
                .catch(function (err) {
                    console.error('Gagal mengubah jumlah:', err);
                    render(old);
                    alert('Terjadi kesalahan. Coba lagi.');
                });
        }

        row.querySelector('.qty-minus').addEventListener('click', function () {
            setQty(parseInt(valueEl.textContent, 10) - 1);
        });
        row.querySelector('.qty-plus').addEventListener('click', function () {
            setQty(parseInt(valueEl.textContent, 10) + 1);
        });

        updateStepper(row);
    });

    window.refreshCart = refresh;
    refresh();
})();
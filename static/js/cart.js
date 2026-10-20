(function () {
    var selectAll = document.getElementById('select-all');
    var stores = document.querySelectorAll('.cart-store');
    var items = document.querySelectorAll('.item-check');
    var totalEl = document.getElementById('summary-total');
    var checkoutCount = document.getElementById('checkout-count');
    var checkoutBtn = document.getElementById('checkout-btn');

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

    function syncChecks() {
        stores.forEach(function (store) {
            var boxes = store.querySelectorAll('.item-check');
            var checked = store.querySelectorAll('.item-check:checked').length;
            setState(store.querySelector('.store-check'), checked === boxes.length, checked === 0);
        });
        var checkedAll = document.querySelectorAll('.item-check:checked').length;
        setState(selectAll, items.length > 0 && checkedAll === items.length, checkedAll === 0);
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

    selectAll.addEventListener('change', function () {
        document.querySelectorAll('.store-check, .item-check').forEach(function (box) {
            box.checked = selectAll.checked;
        });
        refresh();
    });

    stores.forEach(function (store) {
        store.querySelector('.store-check').addEventListener('change', function (e) {
            store.querySelectorAll('.item-check').forEach(function (box) {
                box.checked = e.target.checked;
            });
            refresh();
        });
    });

    items.forEach(function (box) {
        box.addEventListener('change', refresh);
    });

    if (checkoutBtn) {
        checkoutBtn.addEventListener('click', function (e) {
            if (checkoutBtn.classList.contains('is-disabled')) e.preventDefault();
        });
    }

        function updateStepper(row) {
        var qty = parseInt(row.querySelector('.qty-value').textContent, 10) || 1;
        row.querySelector('.qty-minus').disabled = qty <= 1;
    }

    document.querySelectorAll('.cart-item').forEach(function (row) {
        var valueEl = row.querySelector('.qty-value');

        function setQty(n) {
            valueEl.textContent = Math.max(1, n);
            updateStepper(row);
            recalc();
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
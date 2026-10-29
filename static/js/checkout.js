(function () {
    var form = document.getElementById('checkout-form');
    var modal = document.getElementById('addr-modal');
    var fName = document.getElementById('f-name');
    var fPhone = document.getElementById('f-phone');
    var fAddress = document.getElementById('f-address');
    var modalError = document.getElementById('addr-modal-error');
    var summary = document.getElementById('co-summary');

    function rupiah(n) {
        return 'Rp. ' + String(n).replace(/\B(?=(\d{3})+(?!\d))/g, '.');
    }

    function hasAddress() {
        return fName.value.trim() && fPhone.value.trim() && fAddress.value.trim();
    }

    function openModal() {
        modalError.hidden = true;
        modal.hidden = false;
        fName.focus();
    }

    function closeModal() {
        modal.hidden = true;
    }

    function renderAddress() {
        var ok = !!hasAddress();
        document.getElementById('addr-empty').hidden = ok;
        document.getElementById('addr-filled').hidden = !ok;
        document.getElementById('addr-name').textContent = fName.value.trim();
        document.getElementById('addr-phone').textContent = fPhone.value.trim();
        document.getElementById('addr-text').textContent = fAddress.value.trim();
    }

    document.getElementById('addr-change').addEventListener('click', openModal);
    document.getElementById('addr-cancel').addEventListener('click', closeModal);
    document.getElementById('addr-save').addEventListener('click', function () {
        if (!hasAddress()) {
            modalError.hidden = false;
            return;
        }
        renderAddress();
        closeModal();
    });
    modal.addEventListener('click', function (e) {
        if (e.target === modal) closeModal();
    });
    document.addEventListener('keydown', function (e) {
        if (e.key === 'Escape' && !modal.hidden) closeModal();
    });

    // perubahan ongkir dan total saat opsi pengiriman diganti
    function recalc() {
        var picked = form.querySelector('input[name=shipping_method]:checked');
        var perStore = picked ? parseInt(picked.dataset.cost, 10) || 0 : 0;
        var cost = perStore * (parseInt(document.getElementById('co-summary').dataset.storeCount, 10) || 1);
        var items = parseInt(summary.dataset.itemsTotal, 10) || 0;
        document.getElementById('co-shipping').textContent = rupiah(cost);
        document.getElementById('co-grand').textContent = rupiah(items + cost);
    }

    form.querySelectorAll('input[name=shipping_method]').forEach(function (r) {
        r.addEventListener('change', recalc);
    });

    // alamat belum lengkap
    form.addEventListener('submit', function (e) {
        if (!hasAddress()) {
            e.preventDefault();
            openModal();
        }
    });

    renderAddress();
    recalc();
})();

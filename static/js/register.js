document.addEventListener('DOMContentLoaded', () => {
    const form = document.getElementById('registerForm');
    const roleInput = document.getElementById('roleInput');
    const btnPenjual = document.getElementById('btnPenjual');
    const btnPembeli = document.getElementById('btnPembeli');
    const fieldNamaToko = document.getElementById('fieldNamaToko');
    const fieldUsername = document.getElementById('fieldUsername');
    const inputStoreName = document.getElementById('inputStoreName');
    const inputUsername = document.getElementById('inputUsername');
    const btnSendOtp = document.getElementById('btnSendOtp');
    const emailInput = document.getElementById('emailInput');

    // ---- Toggle role Penjual / Pembeli ----
    function switchRole(role) {
        const isSeller = role === 'seller';
        roleInput.value = role;

        btnPenjual.classList.toggle('active', isSeller);
        btnPembeli.classList.toggle('active', !isSeller);

        fieldNamaToko.classList.toggle('hidden', !isSeller);
        fieldUsername.classList.toggle('hidden', isSeller);

        inputStoreName.required = isSeller;
        inputUsername.required = !isSeller;
    }

    btnPenjual.addEventListener('click', () => switchRole('seller'));
    btnPembeli.addEventListener('click', () => switchRole('buyer'));
    switchRole(roleInput.value || 'seller');

    // ---- Kirim OTP (AJAX) ----
    btnSendOtp.addEventListener('click', () => {
        const email = emailInput.value.trim();
        if (!email) {
            alert('Silakan masukkan email terlebih dahulu!');
            return;
        }

        const url = form.dataset.otpUrl;
        const csrfToken = form.querySelector('[name=csrfmiddlewaretoken]').value;

        btnSendOtp.disabled = true;
        btnSendOtp.innerText = 'Sending...';

        fetch(url, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': csrfToken,
            },
            body: JSON.stringify({ email: email }),
        })
            .then(res => res.json())
            .then(data => {
                alert(data.message);
                if (data.success) {
                    startCountdown(60);
                } else {
                    resetOtpButton();
                }
            })
            .catch(() => {
                alert('Terjadi kesalahan koneksi.');
                resetOtpButton();
            });
    });

    function startCountdown(seconds) {
        let countdown = seconds;
        btnSendOtp.innerText = `Ulang (${countdown}s)`;
        const timer = setInterval(() => {
            countdown--;
            btnSendOtp.innerText = `Ulang (${countdown}s)`;
            if (countdown <= 0) {
                clearInterval(timer);
                resetOtpButton();
            }
        }, 1000);
    }

    function resetOtpButton() {
        btnSendOtp.disabled = false;
        btnSendOtp.innerText = 'Kirim OTP';
    }
});
// Toggle lihat/sembunyikan password (ikon mata) - dipakai login & register
document.querySelectorAll('.toggle-pass').forEach(function (btn) {
    btn.addEventListener('click', function () {
        var input = document.getElementById(btn.dataset.target);
        input.type = input.type === 'password' ? 'text' : 'password';
    });
});
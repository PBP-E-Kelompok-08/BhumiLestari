(function () {
    "use strict";

    /**
     * Menormalisasi format input waktu menjadi "HH:MM" 24-jam.
     * Mengganti tanda titik menjadi titik dua dan membatasi rentang jam (00-23) dan menit (00-59).
     * 
     * @param {string} val - Nilai input string dari pengguna (misal "8.30" atau "08:00").
     * @returns {string} String waktu tervalidasi format "HH:MM".
     */
    function normalizeTimeInput(val) {
        var cleaned = String(val || "08:00").trim().replace(".", ":");
        var parts = cleaned.split(":");
        if (parts.length < 2) return "08:00";
        var hh = String(Math.min(23, Math.max(0, parseInt(parts[0], 10) || 0))).padStart(2, "0");
        var mm = String(Math.min(59, Math.max(0, parseInt(parts[1], 10) || 0))).padStart(2, "0");
        return hh + ":" + mm;
    }

    /**
     * Menginisialisasi form pengaturan pesan sambutan bot penjual (Screen 3).
     * Menangani pengiriman formulir via AJAX POST ke `/chat/api/seller/settings/`
     * untuk menyimpan nama bot, pesan sambutan, jam operasional toko, dan pesan toko tutup.
     */
    function initWelcomeSettingsForm() {
        var form = document.getElementById("sellerWelcomeSettingsForm");
        if (!form) return;

        form.addEventListener("submit", async function (e) {
            e.preventDefault();
            var isAuto = document.getElementById("botAutoReplyToggle").checked;
            var botName = document.getElementById("botNameInput").value.trim();
            var welcomeMsg = document.getElementById("welcomeMessageInput").value.trim();
            var startVal = normalizeTimeInput(document.getElementById("operatingStartInput").value);
            var endVal = normalizeTimeInput(document.getElementById("operatingEndInput").value);
            var closedMsg = document.getElementById("closedMessageInput").value.trim();

            try {
                var res = await ChatCore.apiFetch("/chat/api/seller/settings/", {
                    method: "POST",
                    body: {
                        is_auto_reply_enabled: isAuto,
                        bot_name: botName,
                        welcome_message: welcomeMsg,
                        operating_hours_start: startVal,
                        operating_hours_end: endVal,
                        closed_message: closedMsg
                    }
                });
                document.getElementById("operatingStartInput").value = res.settings.operating_hours_start;
                document.getElementById("operatingEndInput").value = res.settings.operating_hours_end;
                ChatCore.showToast(res.message || "Pengaturan sambutan berhasil disimpan.");
            } catch (err) {
                ChatCore.showToast(err.message);
            }
        });
    }

    /**
     * Menginisialisasi manajemen daftar kata kunci dan balasan otomatis penjual (Screen 4).
     * Mencakup penambahan kata kunci baru, pengubahan (edit), penghapusan,
     * serta sakelar aktif/nonaktif (toggle is_active).
     */
    function initKeywordsManagement() {
        var kwForm = document.getElementById("keywordCreateEditForm");
        var kwList = document.getElementById("keywordListContainer");
        var autoReplyToggle = document.getElementById("kwBotAutoReplyToggle");

        if (autoReplyToggle) {
            autoReplyToggle.addEventListener("change", async function () {
                try {
                    await ChatCore.apiFetch("/chat/api/seller/settings/", {
                        method: "POST",
                        body: { is_auto_reply_enabled: autoReplyToggle.checked }
                    });
                    ChatCore.showToast(
                        autoReplyToggle.checked
                            ? "Bot Auto Reply diaktifkan."
                            : "Bot Auto Reply dinonaktifkan."
                    );
                } catch (err) {
                    ChatCore.showToast(err.message);
                }
            });
        }

        if (!kwForm || !kwList) return;

        var editingIdInput = document.getElementById("editingKeywordId");
        var questionInput = document.getElementById("keywordQuestionInput");
        var answerInput = document.getElementById("keywordAnswerInput");
        var submitBtn = document.getElementById("submitKeywordBtn");
        var cancelEditBtn = document.getElementById("cancelEditKeywordBtn");

        /**
         * Mengembalikan formulir penambahan/pengubahan kata kunci ke kondisi awal (tambah baru).
         */
        function resetKeywordForm() {
            editingIdInput.value = "";
            questionInput.value = "";
            answerInput.value = "";
            submitBtn.textContent = "Tambah balasan";
            if (cancelEditBtn) cancelEditBtn.hidden = true;
        }

        if (cancelEditBtn) {
            cancelEditBtn.addEventListener("click", resetKeywordForm);
        }

        /**
         * Memuat ulang daftar kata kunci dari server via GET `/chat/api/seller/knowledge/`
         * dan memperbarui tampilan daftar item secara reaktif.
         */
        async function refreshKeywordsList() {
            try {
                var data = await ChatCore.apiFetch("/chat/api/seller/knowledge/");
                var items = data.knowledges || [];
                if (items.length === 0) {
                    kwList.innerHTML =
                        '<p id="emptyKeywordsText" style="color: #F2EAC0; margin: 4px 0 8px;">Belum ada kata kunci tersimpan. Tambahkan kata kunci baru di bawah.</p>';
                    return;
                }

                var html = "";
                items.forEach(function (k) {
                    html +=
                        '<div class="chat-keyword-item" data-id="' +
                        k.id +
                        '">' +
                        '<div class="chat-keyword-info">' +
                        '<h3 class="chat-keyword-title">' +
                        ChatCore.escapeHtml(k.question) +
                        "</h3>" +
                        '<p class="chat-keyword-answer">' +
                        ChatCore.escapeHtml(k.answer) +
                        "</p>" +
                        "</div>" +
                        '<div class="chat-keyword-actions">' +
                        '<button type="button" class="chat-kw-edit-btn js-edit-kw" data-id="' +
                        k.id +
                        '" data-question="' +
                        ChatCore.escapeHtml(k.question) +
                        '" data-answer="' +
                        ChatCore.escapeHtml(k.answer) +
                        '">Edit</button>' +
                        '<button type="button" class="chat-kw-delete-btn js-delete-kw" data-id="' +
                        k.id +
                        '">Hapus</button>' +
                        '<label class="chat-switch" aria-label="Status Aktif Kata Kunci ' +
                        ChatCore.escapeHtml(k.question) +
                        '">' +
                        '<input type="checkbox" class="js-toggle-kw" data-id="' +
                        k.id +
                        '" ' +
                        (k.is_active ? "checked" : "") +
                        ">" +
                        '<span class="chat-switch-slider"></span>' +
                        "</label>" +
                        "</div>" +
                        "</div>";
                });
                kwList.innerHTML = html;
                bindKeywordItemActions();
            } catch (err) {
                ChatCore.showToast(err.message);
            }
        }

        /**
         * Mengikat event listener untuk tombol edit, tombol hapus, dan sakelar status
         * pada setiap item kata kunci yang ada di DOM.
         */
        function bindKeywordItemActions() {
            kwList.querySelectorAll(".js-edit-kw").forEach(function (btn) {
                btn.addEventListener("click", function () {
                    editingIdInput.value = btn.getAttribute("data-id");
                    questionInput.value = btn.getAttribute("data-question") || "";
                    answerInput.value = btn.getAttribute("data-answer") || "";
                    submitBtn.textContent = "Simpan Perubahan";
                    if (cancelEditBtn) cancelEditBtn.hidden = false;
                    questionInput.focus();
                });
            });

            kwList.querySelectorAll(".js-delete-kw").forEach(function (btn) {
                btn.addEventListener("click", async function () {
                    var id = btn.getAttribute("data-id");
                    if (!id) return;
                    try {
                        var res = await ChatCore.apiFetch("/chat/api/seller/knowledge/" + id + "/", {
                            method: "DELETE"
                        });
                        ChatCore.showToast(res.message || "Kata kunci berhasil dihapus.");
                        if (editingIdInput.value === String(id)) {
                            resetKeywordForm();
                        }
                        await refreshKeywordsList();
                    } catch (err) {
                        ChatCore.showToast(err.message);
                    }
                });
            });

            kwList.querySelectorAll(".js-toggle-kw").forEach(function (chk) {
                chk.addEventListener("change", async function () {
                    var id = chk.getAttribute("data-id");
                    if (!id) return;
                    try {
                        var res = await ChatCore.apiFetch(
                            "/chat/api/seller/knowledge/" + id + "/toggle/",
                            { method: "POST" }
                        );
                        ChatCore.showToast(res.message || "Status kata kunci diperbarui.");
                    } catch (err) {
                        chk.checked = !chk.checked;
                        ChatCore.showToast(err.message);
                    }
                });
            });
        }

        kwForm.addEventListener("submit", async function (e) {
            e.preventDefault();
            var qVal = questionInput.value.trim();
            var aVal = answerInput.value.trim();
            if (!qVal || !aVal) return;

            var editId = editingIdInput.value.trim();
            try {
                if (editId) {
                    var resUpdate = await ChatCore.apiFetch(
                        "/chat/api/seller/knowledge/" + editId + "/",
                        {
                            method: "PUT",
                            body: { question: qVal, answer: aVal }
                        }
                    );
                    ChatCore.showToast(resUpdate.message || "Balasan kata kunci diperbarui.");
                } else {
                    var resCreate = await ChatCore.apiFetch("/chat/api/seller/knowledge/", {
                        method: "POST",
                        body: { question: qVal, answer: aVal, is_active: true }
                    });
                    ChatCore.showToast(resCreate.message || "Balasan kata kunci ditambahkan.");
                }
                resetKeywordForm();
                await refreshKeywordsList();
            } catch (err) {
                ChatCore.showToast(err.message);
            }
        });

        bindKeywordItemActions();
    }

    document.addEventListener("DOMContentLoaded", function () {
        initWelcomeSettingsForm();
        initKeywordsManagement();
    });
})();


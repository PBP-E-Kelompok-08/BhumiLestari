(function () {
    "use strict";

    var state = {
        currentTab: "semua",
        searchQuery: "",
        sessions: [],
        activeSessionId: null,
        activeSessionData: null,
        pollingTimer: null,
        isSending: false,
        pendingMessages: {},
        renderedMessages: []
    };

    var els = {};

    /**
     * Melakukan caching referensi elemen-elemen DOM pada tampilan Obrolan Penjual (Screen 2).
     * Menyimpan elemen daftar obrolan, form composer, header pembeli, dan modal.
     */
    function cacheElements() {
        els.sessionList = document.getElementById("sellerSessionList");
        els.searchForm = document.getElementById("sellerSearchForm");
        els.searchInput = document.getElementById("sellerSearchInput");
        els.tabButtons = document.querySelectorAll(".chat-tab-pill");
        els.buyerTitle = document.getElementById("activeBuyerTitle");
        els.buyerSubtitle = document.getElementById("activeBuyerSubtitle");
        els.messagesContainer = document.getElementById("sellerMessagesContainer");
        els.chatBody = document.getElementById("sellerChatBody");
        els.composerForm = document.getElementById("sellerComposerForm");
        els.messageInput = document.getElementById("sellerMessageInput");
        els.sendBtn = document.getElementById("sellerSendBtn");
        els.contextBar = document.getElementById("sellerProductContextBar");
        els.contextTags = document.getElementById("sellerProductContextTags");
        els.headerMenuBtn = document.getElementById("sellerHeaderMenuBtn");
        els.headerDropdown = document.getElementById("sellerHeaderDropdownMenu");
        els.shell = document.getElementById("chatShell");
    }

    /**
     * Mengambil daftar percakapan pembeli dari endpoint `/chat/api/seller/sessions/`.
     * Mendukung pemfilteran tab (semua, belum_dibaca, arsip) dan query pencarian nama pembeli.
     * @param {boolean} preserveSelection - Jika true, tidak mengubah sesi aktif yang sedang dibuka.
     */
    async function loadSessions(preserveSelection) {
        try {
            var url = "/chat/api/seller/sessions/?tab=" + encodeURIComponent(state.currentTab);
            if (state.searchQuery) {
                url += "&search=" + encodeURIComponent(state.searchQuery);
            }
            var data = await ChatCore.apiFetch(url);
            state.sessions = data.sessions || [];
            renderSessionList();

            if (!preserveSelection && state.sessions.length > 0 && !state.activeSessionId) {
                selectSession(state.sessions[0].id);
            } else if (state.activeSessionId) {
                highlightActiveSessionItem();
            }
        } catch (err) {
            if (els.sessionList) {
                els.sessionList.innerHTML =
                    '<li class="chat-sidebar-empty">Gagal memuat percakapan: ' +
                    ChatCore.escapeHtml(err.message) +
                    "</li>";
            }
        }
    }

    /**
     * Merender daftar percakapan pembeli di sidebar (#sellerSessionList).
     * Menampilkan nama pembeli, preview pesan terakhir, lencana unread, dan tombol arsipkan.
     */
    function renderSessionList() {
        if (!els.sessionList) return;
        if (state.sessions.length === 0) {
            els.sessionList.innerHTML =
                '<li class="chat-sidebar-empty">Belum ada obrolan pembeli pada filter ini.</li>';
            return;
        }

        var html = "";
        state.sessions.forEach(function (s) {
            var isActive = s.id === state.activeSessionId;
            var isUnread = !isActive && (s.unread_count || 0) > 0;
            var buyerName = (s.buyer && (s.buyer.name || s.buyer.email)) || "Pembeli";
            var preview = (s.last_message && s.last_message.content) || "Percakapan baru...";
            preview = preview.replace(/\s+/g, " ").trim();

            html +=
                '<li class="chat-session-item ' +
                (isActive ? "active " : "") +
                (isUnread ? "unread" : "") +
                '" data-session-id="' +
                ChatCore.escapeHtml(s.id) +
                '" tabindex="0" role="button" aria-label="Buka chat dengan ' +
                ChatCore.escapeHtml(buyerName) +
                '">' +
                ChatCore.getAvatarSvgHtml() +
                '<div class="chat-session-info">' +
                '<h3 class="chat-session-title">' +
                ChatCore.escapeHtml(buyerName) +
                "</h3>" +
                '<p class="chat-session-preview">' +
                ChatCore.escapeHtml(preview) +
                "</p>" +
                "</div>" +
                '<div class="chat-session-meta">';

            if (isUnread) {
                html += '<span class="chat-unread-badge">' + s.unread_count + "</span>";
            }

            html +=
                '<button type="button" class="chat-archive-item-btn js-archive-session" data-session-id="' +
                ChatCore.escapeHtml(s.id) +
                '" title="Arsipkan Percakapan" aria-label="Arsipkan Percakapan">' +
                ChatCore.getArchiveIconSvgHtml() +
                "</button>" +
                "</div>" +
                "</li>";
        });

        els.sessionList.innerHTML = html;

        els.sessionList.querySelectorAll(".chat-session-item").forEach(function (item) {
            item.addEventListener("click", function (e) {
                if (e.target.closest(".js-archive-session")) return;
                var sid = item.getAttribute("data-session-id");
                selectSession(sid);
                if (els.shell) els.shell.classList.add("mobile-thread-active");
            });
            item.addEventListener("keydown", function (e) {
                if (e.key === "Enter" || e.key === " ") {
                    e.preventDefault();
                    var sid = item.getAttribute("data-session-id");
                    selectSession(sid);
                }
            });
        });

        els.sessionList.querySelectorAll(".js-archive-session").forEach(function (btn) {
            btn.addEventListener("click", function (e) {
                e.stopPropagation();
                var sid = btn.getAttribute("data-session-id");
                toggleArchiveSession(sid);
            });
        });
    }

    /**
     * Memberikan kelas visual .active pada item sesi pembeli di sidebar yang sedang dibuka.
     */
    function highlightActiveSessionItem() {
        if (!els.sessionList) return;
        els.sessionList.querySelectorAll(".chat-session-item").forEach(function (item) {
            item.classList.toggle("active", item.getAttribute("data-session-id") === state.activeSessionId);
        });
    }

    /**
     * Memilih sesi obrolan pembeli tertentu:
     * 1. Mengambil riwayat pesan via `/chat/api/sessions/<id>/messages/`.
     * 2. Menandai pesan pembeli sebagai telah dibaca di database.
     * 3. Memperbarui informasi header pembeli dan daftar produk terkait.
     * 4. Merender gelembung pesan dan menyinkronkan daftar sesi di sidebar.
     * @param {string} sessionId - UUID sesi percakapan yang dipilih.
     */
    async function selectSession(sessionId) {
        if (!sessionId) return;
        state.activeSessionId = sessionId;
        highlightActiveSessionItem();

        try {
            var data = await ChatCore.apiFetch("/chat/api/sessions/" + sessionId + "/messages/");
            state.activeSessionData = data.session;
            updateHeaderAndContexts(data.session);
            renderMessages(data.messages || [], data.session);
            await loadSessions(true);
        } catch (err) {
            ChatCore.showToast(err.message);
        }
    }

    /**
     * Memperbarui header percakapan dengan nama pembeli serta daftar chip konteks produk
     * yang sedang dikonsultasikan oleh pembeli.
     * @param {object} session - Objek data sesi percakapan dari backend.
     */
    function updateHeaderAndContexts(session) {
        if (!session) return;
        var buyerName = (session.buyer && (session.buyer.name || session.buyer.email)) || "Pembeli";
        if (els.buyerTitle) els.buyerTitle.textContent = buyerName;
        if (els.buyerSubtitle) els.buyerSubtitle.textContent = "Online";

        var contexts = session.product_contexts || [];
        if (els.contextBar && els.contextTags) {
            if (contexts.length > 0) {
                els.contextBar.hidden = false;
                var tagsHtml = '<span class="chat-context-label">Produk Terkait:</span>';
                contexts.forEach(function (c) {
                    var label = c.product_name ? c.product_name + " (" + c.product_id + ")" : c.product_id;
                    tagsHtml +=
                        '<span class="chat-context-chip">' +
                        '<span>' + ChatCore.escapeHtml(label) + '</span>' +
                        '<button type="button" class="chat-context-chip-remove js-remove-context-btn" ' +
                        'data-id="' + ChatCore.escapeHtml(c.product_id) + '" ' +
                        'data-name="' + ChatCore.escapeHtml(c.product_name || c.product_id) + '" ' +
                        'title="Hapus produk terkait ini" aria-label="Hapus ' + ChatCore.escapeHtml(label) + '">&times;</button>' +
                        '</span>';
                });
                els.contextTags.innerHTML = tagsHtml;
                bindSellerContextTagEvents();
            } else {
                els.contextBar.hidden = true;
                els.contextTags.innerHTML = "";
            }
        }
    }
    var renderSessionHeader = updateHeaderAndContexts;

    /**
     * Mengikat pendengar klik untuk tombol silang (hapus) pada chip produk terkait dari sisi penjual.
     */
    function bindSellerContextTagEvents() {
        if (!els.contextTags) return;
        var removeBtns = els.contextTags.querySelectorAll(".js-remove-context-btn");
        removeBtns.forEach(function (btn) {
            btn.addEventListener("click", async function (e) {
                e.stopPropagation();
                if (!state.activeSessionId) return;
                var productId = btn.getAttribute("data-id");
                var productName = btn.getAttribute("data-name");
                try {
                    var url = "/chat/api/sessions/" + state.activeSessionId + "/products/delete/";
                    var res = await ChatCore.apiFetch(url, {
                        method: "POST",
                        body: { product_id: productId }
                    });
                    var remaining = res.all_product_contexts || [];
                    if (state.activeSessionData) {
                        state.activeSessionData.product_contexts = remaining;
                        updateHeaderAndContexts(state.activeSessionData);
                    }
                    state.sessions.forEach(function (s) {
                        if (s.id === state.activeSessionId) {
                            s.product_contexts = remaining;
                        }
                    });
                    ChatCore.showToast("Konteks produk " + (productName || productId) + " dihapus.");
                } catch (err) {
                    ChatCore.showToast("Gagal menghapus konteks: " + err.message);
                }
            });
        });
    }

    /**
     * Membangun kode HTML untuk satu baris gelembung pesan dari perspektif penjual (Seller POV):
     * - Pesan Pembeli: masuk di kiri (.incoming, bubble putih).
     * - Pesan Penjual / Balasan Bot: keluar di kanan (.outgoing, bubble hijau tua).
     * - Pesan Sistem: di tengah (.system).
     * @param {object} m - Objek data pesan.
     * @returns {string} Markup HTML gelembung pesan.
     */
    function createSellerMessageBubbleHtml(m) {
        var timeStr = ChatCore.formatTimeHM(m.created_at);

        if (m.sender_type === "system") {
            return (
                '<div class="chat-bubble-row system">' +
                '<div class="chat-bubble">' +
                ChatCore.escapeHtml(m.content) +
                "</div>" +
                "</div>"
            );
        }

        // In Seller POV (Screen 2):
        // Buyer messages are on the left (incoming, white bubble)
        // Seller / AI messages are on the right (outgoing, dark green bubble)
        var isIncomingBuyer = m.sender_type === "buyer";
        var rowClass = isIncomingBuyer ? "incoming" : "outgoing";
        if (m.is_pending) {
            rowClass += " pending-send";
        }

        var dataAttrs = "";
        if (m.id) {
            dataAttrs += ' data-msg-id="' + ChatCore.escapeHtml(m.id) + '"';
        }
        if (m.temp_id) {
            dataAttrs += ' data-temp-id="' + ChatCore.escapeHtml(m.temp_id) + '"';
        }

        var html = '<div class="chat-bubble-row ' + rowClass + '"' + dataAttrs + '>';
        html += '<div class="chat-bubble">';

        if (m.sender_type === "ai") {
            html += '<span class="chat-bot-sender-name" style="color: #F2EAC0;">Balasan Bot Otomatis</span>';
        }

        html += ChatCore.escapeHtml(m.content);
        html += "</div>";

        if (timeStr) {
            html += '<span class="chat-bubble-time">' + ChatCore.escapeHtml(timeStr) + "</span>";
        }
        html += "</div>";
        return html;
    }

    /**
     * Menggulung scroll kontainer pesan penjual (#sellerChatBody) ke bagian paling dasar.
     */
    function scrollToBottom() {
        if (els.chatBody) {
            els.chatBody.scrollTop = els.chatBody.scrollHeight;
        }
    }

    /**
     * Memperbarui cuplikan teks pesan terakhir di sidebar obrolan penjual secara instan (0ms).
     * @param {string} sessionId - UUID sesi obrolan yang aktif.
     * @param {string} text - Isi teks balasan yang dikirim.
     */
    function updateSessionPreview(sessionId, text) {
        if (!sessionId || !text) return;
        var cleanText = text.replace(/\s+/g, " ").trim();
        var session = state.sessions.find(function (s) { return s.id === sessionId; });
        if (session) {
            session.last_message = {
                content: cleanText,
                created_at: new Date().toISOString()
            };
        }
        if (els.sessionList) {
            var item = els.sessionList.querySelector('[data-session-id="' + sessionId + '"]');
            if (item) {
                var previewEl = item.querySelector(".chat-session-preview");
                if (previewEl) {
                    previewEl.textContent = cleanText;
                }
            }
        }
    }

    /**
     * Menghapus pesan sementara dari daftar pendingMessages setelah server berhasil menyimpannya.
     * @param {string} sessionId - UUID sesi obrolan aktif.
     * @param {string} tempId - ID sementara pesan yang baru tersimpan.
     */
    function removePendingMessage(sessionId, tempId) {
        if (!state.pendingMessages || !state.pendingMessages[sessionId]) return;
        state.pendingMessages[sessionId] = state.pendingMessages[sessionId].filter(function (p) {
            return p.temp_id !== tempId && p.id !== tempId;
        });
    }

    /**
     * Menghilangkan pesan-pesan duplikat berdasarkan ID unik dan signature konten pesan.
     * @param {Array} messages - Daftar pesan mentah gabungan.
     * @returns {Array} Daftar pesan unik tanpa duplikasi.
     */
    function deduplicateMessages(messages) {
        var seenIds = new Set();
        var seenSignatures = new Set();
        var result = [];

        messages.forEach(function (m) {
            if (m.id && seenIds.has(m.id)) {
                return;
            }
            var sig = m.sender_type + "::" + (m.content || "").trim();
            if (m.temp_id && seenSignatures.has(sig)) {
                return;
            }

            if (m.id) seenIds.add(m.id);
            seenSignatures.add(sig);
            result.push(m);
        });

        return result;
    }

    /**
     * Merekonsiliasi pesan dari respons polling server dengan pesan sementara (in-flight):
     * - Memeriksa apakah pesan pending sudah tersimpan di database server.
     * - Menyisakan pesan pending yang masih dalam transmisi jaringan agar tidak hilang/berkedip.
     * @param {Array} serverMessages - Daftar pesan yang baru diambil dari database server.
     * @param {string} sessionId - UUID sesi aktif saat polling.
     * @returns {Array} Daftar pesan hasil rekonsiliasi yang siap dirender.
     */
    function reconcileServerMessages(serverMessages, sessionId) {
        var pending = (state.pendingMessages && state.pendingMessages[sessionId]) || [];
        if (!pending || pending.length === 0) {
            return serverMessages;
        }

        var remainingPending = [];
        pending.forEach(function (p) {
            var matched = serverMessages.some(function (sm) {
                if (sm.id && sm.id === p.id) return true;
                if (sm.sender_type === p.sender_type && (sm.content || "").trim() === (p.content || "").trim()) {
                    var pTime = new Date(p.created_at).getTime();
                    var sTime = new Date(sm.created_at).getTime();
                    if (isNaN(pTime) || isNaN(sTime) || Math.abs(pTime - sTime) < 90000) {
                        return true;
                    }
                }
                return false;
            });
            if (!matched) {
                remainingPending.push(p);
            }
        });

        state.pendingMessages[sessionId] = remainingPending;
        return deduplicateMessages(serverMessages.concat(remainingPending));
    }

    /**
     * Membandingkan array pesan saat ini dengan array pesan baru dari server:
     * Mengembalikan true hanya jika terjadi penambahan pesan baru atau perubahan konten.
     * Digunakan oleh polling untuk menghindari render ulang DOM jika tidak ada pesan baru.
     * @param {Array} oldMsgs - Daftar pesan yang sedang dirender di layar.
     * @param {Array} newMsgs - Daftar pesan hasil polling server.
     * @returns {boolean} True jika ada perubahan pesan yang perlu dirender ulang.
     */
    function haveMessagesChanged(oldMsgs, newMsgs) {
        if (!oldMsgs || !newMsgs) return true;
        if (oldMsgs.length !== newMsgs.length) return true;
        for (var i = 0; i < oldMsgs.length; i++) {
            if (oldMsgs[i].id !== newMsgs[i].id || oldMsgs[i].content !== newMsgs[i].content) {
                return true;
            }
        }
        return false;
    }

    /**
     * Merender seluruh gelembung pesan ke kontainer pesan penjual (#sellerMessagesContainer)
     * dan menggulung layar ke pesan terbaru.
     * @param {Array} messages - Array objek pesan.
     * @param {object} session - Data sesi obrolan aktif.
     */
    function renderMessages(messages, session) {
        if (!els.messagesContainer) return;
        if (!messages || messages.length === 0) {
            els.messagesContainer.innerHTML =
                '<div class="chat-state-box">' +
                '<h2 class="chat-state-title">Belum Ada Pesan</h2>' +
                '<p class="chat-state-desc">Kirim pesan balasan untuk menyapa pembeli ini.</p>' +
                "</div>";
            state.renderedMessages = [];
            return;
        }

        var html = "";
        messages.forEach(function (m) {
            html += createSellerMessageBubbleHtml(m);
        });

        els.messagesContainer.innerHTML = html;
        state.renderedMessages = messages.slice();
        scrollToBottom();
    }

    /**
     * Membuka modal pelaporan aduan pembeli bermasalah (#reportModalBackdrop)
     * dan mengisikan ID pembeli yang bersangkutan secara otomatis.
     */
    function openReportBuyerModal() {
        if (!state.activeSessionData || !state.activeSessionData.buyer) {
            ChatCore.showToast("Pilih percakapan pembeli terlebih dahulu.");
            return;
        }
        document.getElementById("reportedUserIdInput").value = state.activeSessionData.buyer.id;
        document.getElementById("reportReasonInput").value = "";
        ChatCore.openModal("reportModalBackdrop");
    }

    /**
     * Mengirim balasan langsung penjual ke pembeli:
     * 1. Validasi input & perlindungan ganda terhadap double submit (`state.isSending`).
     * 2. Optimistic UI: Menampilkan gelembung balasan hijau seketika dengan ID sementara (temp_id).
     * 3. Mengirimkan request POST ke `/chat/api/sessions/<id>/direct-send/`.
     * 4. Merekonsiliasi data-temp-id dengan ID database resmi setelah server membalas sukses (tanpa session refresh).
     * @param {Event} e - Event submit formulir composer.
     */
    async function handleSendDirectReply(e) {
        if (e) e.preventDefault();
        if (!els.messageInput) return;
        var text = els.messageInput.value.trim();
        if (!text) return;

        // Prevent double submit
        if (state.isSending) return;

        if (!state.activeSessionId) {
            ChatCore.showToast("Pilih percakapan pembeli terlebih dahulu.");
            return;
        }

        var currentSessionId = state.activeSessionId;

        // 1. Immediately clear input & disable send button
        els.messageInput.value = "";
        state.isSending = true;
        if (els.sendBtn) els.sendBtn.disabled = true;

        // 2. Generate tempId & create optimistic message
        var tempId = "temp_" + Date.now() + "_" + Math.floor(Math.random() * 1000000);
        var optimisticMsg = {
            id: tempId,
            temp_id: tempId,
            sender_type: "seller",
            content: text,
            created_at: new Date().toISOString(),
            is_pending: true
        };

        // 3. Track pending
        if (!state.pendingMessages) state.pendingMessages = {};
        if (!state.pendingMessages[currentSessionId]) {
            state.pendingMessages[currentSessionId] = [];
        }
        state.pendingMessages[currentSessionId].push(optimisticMsg);

        // 4. Remove empty state if present
        var emptyBox = els.messagesContainer ? els.messagesContainer.querySelector(".chat-state-box") : null;
        if (emptyBox) {
            emptyBox.remove();
        }

        // 5. Instantly render optimistic bubble in DOM
        if (els.messagesContainer) {
            var bubbleHtml = createSellerMessageBubbleHtml(optimisticMsg);
            els.messagesContainer.insertAdjacentHTML("beforeend", bubbleHtml);
        }

        if (!Array.isArray(state.renderedMessages)) {
            state.renderedMessages = [];
        }
        state.renderedMessages.push(optimisticMsg);

        // 6. Scroll to bottom immediately
        scrollToBottom();

        // 7. Update sidebar preview immediately
        updateSessionPreview(currentSessionId, text);

        try {
            var res = await ChatCore.apiFetch("/chat/api/sessions/" + currentSessionId + "/direct-send/", {
                method: "POST",
                body: { content: text }
            });

            removePendingMessage(currentSessionId, tempId);

            if (state.activeSessionId === currentSessionId && res.message) {
                optimisticMsg.id = res.message.id;
                optimisticMsg.is_pending = false;
                optimisticMsg.created_at = res.message.created_at;

                if (els.messagesContainer) {
                    var optBubble = els.messagesContainer.querySelector('[data-temp-id="' + tempId + '"]');
                    if (optBubble) {
                        optBubble.setAttribute("data-msg-id", res.message.id);
                        optBubble.removeAttribute("data-temp-id");
                        optBubble.classList.remove("pending-send");
                        var timeEl = optBubble.querySelector(".chat-bubble-time");
                        if (timeEl && res.message.created_at) {
                            timeEl.textContent = ChatCore.formatTimeHM(res.message.created_at);
                        }
                    }
                }
            }
        } catch (err) {
            removePendingMessage(currentSessionId, tempId);
            if (els.messagesContainer) {
                var failedBubble = els.messagesContainer.querySelector('[data-temp-id="' + tempId + '"]');
                if (failedBubble) {
                    failedBubble.style.opacity = "0.55";
                    failedBubble.title = "Gagal terkirim: " + err.message;
                }
            }
            ChatCore.showToast(err.message || "Gagal mengirim balasan.");
        } finally {
            state.isSending = false;
            if (els.sendBtn) els.sendBtn.disabled = false;
            if (els.messageInput) els.messageInput.focus();
        }
    }

    /**
     * Mengarsipkan atau membatalkan pengarsipan sesi percakapan pembeli
     * melalui pemanggilan POST `/chat/api/sessions/<id>/archive/`.
     * @param {string} [sessionId] - UUID sesi target (default: state.activeSessionId).
     */
    async function toggleArchiveSession(sessionId) {
        var targetId = sessionId || state.activeSessionId;
        if (!targetId) return;
        try {
            var res = await ChatCore.apiFetch("/chat/api/sessions/" + targetId + "/archive/", {
                method: "POST"
            });
            ChatCore.showToast(res.is_archived ? "Percakapan diarsipkan." : "Percakapan dikembalikan.");
            if (state.activeSessionId === targetId) {
                state.activeSessionId = null;
            }
            await loadSessions(false);
        } catch (err) {
            ChatCore.showToast(err.message);
        }
    }

    /**
     * Mengikat seluruh pendengar event interaktif pada halaman obrolan penjual:
     * - Pencarian obrolan pembeli.
     * - Tab filter inbox (Semua / Belum Dibaca / Arsip).
     * - Form composer balasan langsung ke pembeli.
     * - Menu dropdown header dan modal pelaporan pembeli.
     */
    function bindEvents() {
        if (els.searchForm) {
            els.searchForm.addEventListener("submit", function (e) {
                e.preventDefault();
                state.searchQuery = els.searchInput ? els.searchInput.value.trim() : "";
                loadSessions(true);
            });
        }

        els.tabButtons.forEach(function (btn) {
            btn.addEventListener("click", function () {
                els.tabButtons.forEach(function (b) {
                    b.classList.remove("active");
                    b.setAttribute("aria-selected", "false");
                });
                btn.classList.add("active");
                btn.setAttribute("aria-selected", "true");
                state.currentTab = btn.getAttribute("data-tab") || "semua";
                state.activeSessionId = null;
                loadSessions(false);
            });
        });

        if (els.composerForm) {
            els.composerForm.addEventListener("submit", handleSendDirectReply);
        }

        if (els.headerMenuBtn && els.headerDropdown) {
            els.headerMenuBtn.addEventListener("click", function (e) {
                e.stopPropagation();
                var isHidden = els.headerDropdown.hidden;
                els.headerDropdown.hidden = !isHidden;
                els.headerMenuBtn.setAttribute("aria-expanded", String(isHidden));
            });
            document.addEventListener("click", function () {
                els.headerDropdown.hidden = true;
                els.headerMenuBtn.setAttribute("aria-expanded", "false");
            });
        }

        var reportTriggers = [
            document.getElementById("sellerHeaderReportBtn"),
            document.getElementById("sellerDropdownReportBtn")
        ];
        reportTriggers.forEach(function (btn) {
            if (!btn) return;
            btn.addEventListener("click", openReportBuyerModal);
        });

        var reportForm = document.getElementById("reportModalForm");
        if (reportForm) {
            reportForm.addEventListener("submit", async function (e) {
                e.preventDefault();
                var reportedId = document.getElementById("reportedUserIdInput").value;
                var reasonVal = document.getElementById("reportReasonInput").value.trim();
                if (!reportedId || !reasonVal) return;
                try {
                    var res = await ChatCore.apiFetch("/chat/api/reports/", {
                        method: "POST",
                        body: {
                            reported_user_id: parseInt(reportedId, 10),
                            session_id: state.activeSessionId,
                            reason: reasonVal
                        }
                    });
                    ChatCore.closeModal("reportModalBackdrop");
                    ChatCore.showToast(res.message || "Laporan terhadap pembeli telah dikirim.");
                } catch (err) {
                    ChatCore.showToast(err.message);
                }
            });
        }

        var archiveDropdownBtn = document.getElementById("sellerDropdownArchiveBtn");
        if (archiveDropdownBtn) {
            archiveDropdownBtn.addEventListener("click", function () {
                toggleArchiveSession(state.activeSessionId);
            });
        }

        var sellerCallBtn = document.getElementById("sellerHeaderCallBtn");
        if (sellerCallBtn) {
            sellerCallBtn.addEventListener("click", function () {
                if (!state.activeSessionData || !state.activeSessionData.buyer) {
                    ChatCore.showToast("Pilih sesi pembeli untuk melihat detail.");
                    return;
                }
                var rating = state.activeSessionData.rating;
                if (rating && rating.rating) {
                    ChatCore.showToast("Rating pembeli: " + rating.rating + "★ " + (rating.feedback ? '("' + rating.feedback + '")' : ""));
                } else {
                    ChatCore.showToast(
                        "Pembeli: " +
                            (state.activeSessionData.buyer.name || state.activeSessionData.buyer.email) +
                            " (Belum ada rating)"
                    );
                }
            });
        }

        var sellerPlusBtn = document.getElementById("sellerPlusBtn");
        if (sellerPlusBtn) {
            sellerPlusBtn.addEventListener("click", function () {
                if (state.activeSessionId) {
                    selectSession(state.activeSessionId);
                    ChatCore.showToast("Percakapan diperbarui.");
                }
            });
        }
    }

    /**
     * Fungsi inisialisasi utama obrolan penjual (Screen 2):
     * 1. Caching elemen DOM dan pengikatan event listener.
     * 2. Pemuatan sesi awal dari server.
     * 3. Pengaktifan background smart polling (interval 6 detik)
     *    dengan rekonsiliasi pesan anti-duplikasi dan deteksi perubahan (anti-flicker).
     */
    async function init() {
        cacheElements();
        bindEvents();
        await loadSessions(false);

        // Poll every 6 seconds to keep messages fresh without flashing or duplicates
        state.pollingTimer = setInterval(function () {
            if (state.activeSessionId && !state.isSending) {
                var currentSessionId = state.activeSessionId;
                ChatCore.apiFetch("/chat/api/sessions/" + currentSessionId + "/messages/")
                    .then(function (data) {
                        if (state.activeSessionId !== currentSessionId) return;
                        state.activeSessionData = data.session;
                        var combined = reconcileServerMessages(data.messages || [], currentSessionId);
                        if (haveMessagesChanged(state.renderedMessages, combined)) {
                            renderMessages(combined, data.session);
                        }
                    })
                    .catch(function () {});
            }
        }, 6000);
    }

    document.addEventListener("DOMContentLoaded", init);
})();


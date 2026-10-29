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
     * Melakukan caching referensi elemen-elemen DOM pada tampilan Obrolan Pembeli (Screen 1 & 5).
     * Menyimpan elemen daftar sesi, form pencarian, header toko, gelembung pesan, dan form input.
     */
    function cacheElements() {
        els.sessionList = document.getElementById("buyerSessionList");
        els.searchForm = document.getElementById("buyerSearchForm");
        els.searchInput = document.getElementById("buyerSearchInput");
        els.tabButtons = document.querySelectorAll(".chat-tab-pill");
        els.storeTitle = document.getElementById("activeStoreTitle");
        els.storeSubtitle = document.getElementById("activeStoreSubtitle");
        els.messagesContainer = document.getElementById("buyerMessagesContainer");
        els.chatBody = document.getElementById("buyerChatBody");
        els.composerForm = document.getElementById("buyerComposerForm");
        els.messageInput = document.getElementById("buyerMessageInput");
        els.sendBtn = document.getElementById("buyerSendBtn");
        els.contextBar = document.getElementById("productContextBar");
        els.contextTags = document.getElementById("productContextTags");
        els.contextChips = document.getElementById("productContextChips");
        els.headerMenuBtn = document.getElementById("headerMenuBtn");
        els.headerDropdown = document.getElementById("headerDropdownMenu");
        els.shell = document.getElementById("chatShell");
    }

    /**
     * Mengambil daftar percakapan pembeli dari backend `/chat/api/buyer/sessions/`.
     * Mendukung pemfilteran tab (Semua, Belum Dibaca, Arsip) dan query pencarian nama toko.
     * @param {boolean} preserveSelection - Jika true, tidak mengubah sesi aktif yang sedang dibuka.
     */
    async function loadSessions(preserveSelection) {
        try {
            var url = "/chat/api/buyer/sessions/?tab=" + encodeURIComponent(state.currentTab);
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
     * Merender daftar percakapan toko di sidebar pembeli (#buyerSessionList).
     * Menampilkan nama toko, cuplikan pesan terakhir, lencana belum dibaca, dan tombol arsipkan.
     */
    function renderSessionList() {
        if (!els.sessionList) return;
        if (state.sessions.length === 0) {
            els.sessionList.innerHTML =
                '<li class="chat-sidebar-empty">Tidak ada percakapan pada tab ini. Klik + untuk memulai chat dengan toko.</li>';
            return;
        }

        var html = "";
        state.sessions.forEach(function (s) {
            var isActive = s.id === state.activeSessionId;
            var isUnread = !isActive && (s.unread_count || 0) > 0;
            var storeName = (s.seller && s.seller.store_name) || "Toko BhumiLestari";
            var preview = (s.last_message && s.last_message.content) || "Mulai percakapan...";
            preview = preview.replace(/\s+/g, " ").trim();

            html +=
                '<li class="chat-session-item ' +
                (isActive ? "active " : "") +
                (isUnread ? "unread" : "") +
                '" data-session-id="' +
                ChatCore.escapeHtml(s.id) +
                '" tabindex="0" role="button" aria-label="Buka percakapan dengan ' +
                ChatCore.escapeHtml(storeName) +
                '">' +
                ChatCore.getAvatarSvgHtml() +
                '<div class="chat-session-info">' +
                '<h3 class="chat-session-title">' +
                ChatCore.escapeHtml(storeName) +
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
                '" title="' +
                (s.is_archived ? "Buka Arsip" : "Arsipkan Percakapan") +
                '" aria-label="Arsipkan Percakapan">' +
                ChatCore.getArchiveIconSvgHtml() +
                "</button>" +
                "</div>" +
                "</li>";
        });

        els.sessionList.innerHTML = html;

        // Bind session click and archive click
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
     * Memberikan penanda visual kelas CSS .active pada kartu sesi toko di sidebar yang sedang dipilih.
     */
    function highlightActiveSessionItem() {
        if (!els.sessionList) return;
        els.sessionList.querySelectorAll(".chat-session-item").forEach(function (item) {
            item.classList.toggle("active", item.getAttribute("data-session-id") === state.activeSessionId);
        });
    }

    /**
     * Memilih sesi percakapan toko aktif:
     * 1. Mengambil riwayat pesan dan data sesi via `/chat/api/sessions/<id>/messages/`.
     * 2. Menandai pesan dari penjual/AI sebagai telah dibaca.
     * 3. Memperbarui judul toko, subtitle online, tombol eskalasi, dan bar konteks produk.
     * 4. Merender gelembung pesan dan menyinkronkan status sidebar.
     * @param {string} sessionId - UUID sesi obrolan yang dipilih.
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
     * Memperbarui antarmuka header ruang obrolan (Screen 1 & 5):
     * - Nama toko dan status terhubung (Asisten AI atau Penjual Langsung).
     * - Menyesuaikan opsi menu dropdown: "Hubungi Penjual" (pada sesi AI) atau "Beralih ke Bot AI" (pada sesi Direct).
     * - Menampilkan chip konteks produk yang sedang ditanyakan pembeli.
     * @param {object} session - Data sesi obrolan aktif.
     */
    function updateHeaderAndContexts(session) {
        if (!session) return;
        var storeName = (session.seller && session.seller.store_name) || "Toko";
        if (els.storeTitle) els.storeTitle.textContent = storeName;
        if (els.storeSubtitle) {
            els.storeSubtitle.textContent =
                session.session_type === "ai" ? "Online" : "Online • Terhubung dengan Penjual";
        }

        var dropdownEscalate = document.getElementById("dropdownEscalateBtn");
        var dropdownSwitchAi = document.getElementById("dropdownSwitchAiBtn");
        if (dropdownEscalate) {
            dropdownEscalate.style.display = (session.session_type === "ai" && session.status === "active") ? "block" : "none";
        }
        if (dropdownSwitchAi) {
            dropdownSwitchAi.style.display = (session.session_type === "direct" && session.status === "active") ? "block" : "none";
        }

        var contexts = session.product_contexts || [];
        if (els.contextBar) {
            // Selalu tampilkan bar konteks produk selama sesi percakapan aktif, meskipun konteks kosong
            els.contextBar.hidden = false;
        }

        var chipsEl = els.contextChips || document.getElementById("productContextChips");
        if (chipsEl) {
            var chipsHtml = "";
            contexts.forEach(function (c) {
                var label = c.product_name ? c.product_name + " (" + c.product_id + ")" : c.product_id;
                chipsHtml +=
                    '<span class="chat-context-chip">' +
                    '<span>' + ChatCore.escapeHtml(label) + '</span>' +
                    '<button type="button" class="chat-context-chip-remove js-remove-context-btn" ' +
                    'data-id="' + ChatCore.escapeHtml(c.product_id) + '" ' +
                    'data-name="' + ChatCore.escapeHtml(c.product_name || c.product_id) + '" ' +
                    'title="Hapus produk terkait ini" aria-label="Hapus ' + ChatCore.escapeHtml(label) + '">&times;</button>' +
                    '</span>';
            });
            chipsEl.innerHTML = chipsHtml;
            bindContextTagEvents();
        }
    }

    /**
     * Mengikat pendengar klik pada tombol hapus chip produk terkait (×) di bawah header.
     */
    function bindContextTagEvents() {
        var chipsEl = els.contextChips || document.getElementById("productContextChips");
        if (!chipsEl) return;
        var removeBtns = chipsEl.querySelectorAll(".js-remove-context-btn");
        removeBtns.forEach(function (btn) {
            btn.addEventListener("click", function (e) {
                e.stopPropagation();
                var productId = btn.getAttribute("data-id");
                var productName = btn.getAttribute("data-name");
                removeProductContext(productId, productName);
            });
        });
    }

    /**
     * Menghapus keterkaitan satu produk tertentu dari sesi obrolan pembeli
     * via POST `/chat/api/sessions/<id>/products/delete/`.
     * @param {string} productId - ID produk yang ingin dilepas dari sesi.
     * @param {string} productName - Nama produk untuk label notifikasi toast.
     */
    async function removeProductContext(productId, productName) {
        if (!state.activeSessionId) return;
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
    }

    /**
     * Membangun string HTML gelembung pesan dari perspektif pembeli (Buyer POV):
     * - Pesan Pembeli: keluar di kanan (.outgoing, bubble hijau tua).
     * - Pesan AI / Penjual: masuk di kiri (.incoming, bubble putih).
     * - Pesan Sistem: di tengah (.system).
     * - Menyisipkan label nama bot dan tombol eskalasi "Hubungi Penjual" pada gelembung AI terakhir.
     * @param {object} m - Objek data pesan.
     * @param {boolean} isAiSession - True jika sesi aktif adalah sesi AI.
     * @param {boolean} isLastAi - True jika pesan ini adalah pesan AI paling akhir dalam riwayat.
     * @returns {string} Markup HTML gelembung pesan.
     */
    function createMessageBubbleHtml(m, isAiSession, isLastAi) {
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

        var isOutgoing = m.sender_type === "buyer";
        var rowClass = isOutgoing ? "outgoing" : "incoming";
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
            var botLabel = "EucalypBot";
            var signMatch = (m.content || "").match(/-([A-Za-z0-9_]+Bot)\s*$/i);
            if (signMatch) {
                botLabel = signMatch[1];
            }
            html += '<span class="chat-bot-sender-name">' + ChatCore.escapeHtml(botLabel) + "</span>";
        }

        html += ChatCore.escapeHtml(m.content);

        // Show "Hubungi Penjual" button inside AI message bubble when in active AI session
        if (isAiSession && m.sender_type === "ai" && isLastAi) {
            html +=
                '<div class="chat-bubble-actions">' +
                '<button type="button" class="chat-pill-btn-olive js-escalate-seller">Hubungi Penjual</button>' +
                "</div>";
        }

        html += "</div>";
        if (timeStr) {
            html += '<span class="chat-bubble-time">' + ChatCore.escapeHtml(timeStr) + "</span>";
        }
        html += "</div>";
        return html;
    }

    /**
     * Mengikat pendengar klik pada tombol eskalasi "Hubungi Penjual" (.js-escalate-seller)
     * yang berada di dalam gelembung pesan AI.
     */
    function bindEscalateButtons() {
        if (!els.messagesContainer) return;
        els.messagesContainer.querySelectorAll(".js-escalate-seller").forEach(function (btn) {
            btn.onclick = function () {
                escalateToSeller();
            };
        });
    }

    /**
     * Menampilkan gelembung indikator mengetik (3 titik memantul)
     * saat asisten bot AI sedang memproses jawaban.
     * @param {string} [botName] - Nama bot (misal "EucalypBot").
     */
    function showTypingIndicator(botName) {
        if (!els.messagesContainer) return;
        hideTypingIndicator();
        var label = botName || "EucalypBot";
        var html =
            '<div id="aiTypingIndicator" class="chat-bubble-row incoming">' +
            '<div class="chat-bubble chat-typing-indicator">' +
            '<span class="chat-bot-sender-name" style="margin-right: 6px;">' + ChatCore.escapeHtml(label) + '</span>' +
            '<span>mengetik balasan</span>' +
            '<span class="chat-typing-dots">' +
            '<span class="chat-typing-dot"></span>' +
            '<span class="chat-typing-dot"></span>' +
            '<span class="chat-typing-dot"></span>' +
            '</span>' +
            '</div>' +
            '</div>';
        els.messagesContainer.insertAdjacentHTML("beforeend", html);
        scrollToBottom();
    }

    /**
     * Menghapus elemen indikator mengetik AI (#aiTypingIndicator) dari DOM.
     */
    function hideTypingIndicator() {
        var el = document.getElementById("aiTypingIndicator");
        if (el) el.remove();
    }

    /**
     * Menggulung scroll kontainer obrolan pembeli (#buyerChatBody) ke dasar.
     */
    function scrollToBottom() {
        if (els.chatBody) {
            els.chatBody.scrollTop = els.chatBody.scrollHeight;
        }
    }

    /**
     * Memperbarui cuplikan teks pesan terakhir pada kartu sesi di sidebar pembeli secara instan.
     * @param {string} sessionId - UUID sesi aktif.
     * @param {string} text - Teks pesan yang baru dikirim.
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
     * Menghapus pesan sementara dari `state.pendingMessages` setelah server berhasil membalas.
     * @param {string} sessionId - UUID sesi aktif.
     * @param {string} tempId - ID sementara pesan yang tersimpan.
     */
    function removePendingMessage(sessionId, tempId) {
        if (!state.pendingMessages || !state.pendingMessages[sessionId]) return;
        state.pendingMessages[sessionId] = state.pendingMessages[sessionId].filter(function (p) {
            return p.temp_id !== tempId && p.id !== tempId;
        });
    }

    /**
     * Menyaring dan menghilangkan pesan duplikat berdasarkan ID unik dan signature konten.
     * @param {Array} messages - Daftar pesan gabungan.
     * @returns {Array} Daftar pesan unik.
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
     * Merekonsiliasi pesan dari respons polling server dengan pesan sementara pembeli (in-flight)
     * agar pesan yang baru dikirim tidak hilang atau berkedip saat polling berkala tiba.
     * @param {Array} serverMessages - Pesan dari server.
     * @param {string} sessionId - UUID sesi aktif.
     * @returns {Array} Pesan gabungan unik.
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
     * Mengecek apakah ada perbedaan antara array pesan yang sedang tampil di layar dengan array pesan baru dari server.
     * Mencegah rendering ulang DOM berulang kali saat polling jika tidak ada data baru (anti-flicker).
     * @param {Array} oldMsgs - Array pesan lama.
     * @param {Array} newMsgs - Array pesan baru.
     * @returns {boolean} True jika pesan berubah.
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
     * Merender seluruh gelembung pesan ke kontainer pesan pembeli (#buyerMessagesContainer),
     * mengikat tombol eskalasi di pesan AI, dan menggulung scroll ke pesan terbawah.
     * @param {Array} messages - Daftar pesan.
     * @param {object} session - Data sesi obrolan aktif.
     */
    function renderMessages(messages, session) {
        if (!els.messagesContainer) return;
        if (!messages || messages.length === 0) {
            els.messagesContainer.innerHTML =
                '<div class="chat-state-box">' +
                '<h2 class="chat-state-title">Mulai Percakapan</h2>' +
                '<p class="chat-state-desc">Ketik pertanyaan Anda di bawah untuk menanyakan stok, bahan, atau pengiriman produk.</p>' +
                "</div>";
            state.renderedMessages = [];
            return;
        }

        var isAiSession = session && session.session_type === "ai" && session.status === "active";
        var lastAiIndex = -1;
        messages.forEach(function (m, idx) {
            if (m.sender_type === "ai") lastAiIndex = idx;
        });

        var html = "";
        messages.forEach(function (m, idx) {
            html += createMessageBubbleHtml(m, isAiSession, idx === lastAiIndex);
        });

        els.messagesContainer.innerHTML = html;
        state.renderedMessages = messages.slice();
        bindEscalateButtons();
        scrollToBottom();
    }

    /**
     * Mengirimkan pesan pembeli ke asisten AI atau ke penjual langsung:
     * 1. Perlindungan ganda terhadap double-submit (`state.isSending`).
     * 2. Optimistic UI (0ms): Gelembung pesan keluar langsung muncul di layar dengan temp_id.
     * 3. Menampilkan animasi indikator mengetik jika sesi bertipe AI.
     * 4. Memanggil endpoint `/send/` (untuk AI) atau `/direct-send/` (untuk penjual).
     * 5. Menangani eskalasi cerdas jika balasan AI memicu sinyal handover (`res.handover == true`).
     * 6. Menempelkan balasan AI atau memperbarui ID resmi database tanpa refresh sesi penuh.
     * @param {Event} e - Event submit formulir composer pembeli.
     */
    async function handleSendMessage(e) {
        if (e) e.preventDefault();
        if (!els.messageInput) return;
        var text = els.messageInput.value.trim();
        if (!text) return;

        // Prevent double send if an in-flight request is pending
        if (state.isSending) return;

        if (!state.activeSessionId || !state.activeSessionData) {
            ChatCore.openModal("productContextModalBackdrop");
            ChatCore.showToast("Pilih toko terlebih dahulu untuk mengirim pesan.");
            return;
        }

        var currentSessionId = state.activeSessionId;
        var isAi = state.activeSessionData.session_type === "ai" && state.activeSessionData.status === "active";
        var endpoint = isAi
            ? "/chat/api/sessions/" + currentSessionId + "/send/"
            : "/chat/api/sessions/" + currentSessionId + "/direct-send/";

        // 1. Immediately clear input & disable send button to prevent double-submit
        els.messageInput.value = "";
        state.isSending = true;
        if (els.sendBtn) els.sendBtn.disabled = true;

        // 2. Generate unique tempId & create optimistic message
        var tempId = "temp_" + Date.now() + "_" + Math.floor(Math.random() * 1000000);
        var optimisticMsg = {
            id: tempId,
            temp_id: tempId,
            sender_type: "buyer",
            content: text,
            created_at: new Date().toISOString(),
            is_pending: true
        };

        // 3. Track pending message to avoid duplication during server polling
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

        // 5. Instantly render optimistic outgoing bubble in DOM
        if (els.messagesContainer) {
            var bubbleHtml = createMessageBubbleHtml(optimisticMsg, isAi, false);
            els.messagesContainer.insertAdjacentHTML("beforeend", bubbleHtml);
        }

        // Update in-memory rendered messages
        if (!Array.isArray(state.renderedMessages)) {
            state.renderedMessages = [];
        }
        state.renderedMessages.push(optimisticMsg);

        // 6. Scroll to bottom immediately
        scrollToBottom();

        // 7. Update sidebar session preview immediately
        updateSessionPreview(currentSessionId, text);

        // 8. If AI session, show typing indicator right below the sent bubble
        if (isAi) {
            showTypingIndicator("EucalypBot");
        }

        try {
            var res = await ChatCore.apiFetch(endpoint, {
                method: "POST",
                body: { content: text }
            });

            // Hide typing indicator
            hideTypingIndicator();

            // If session switched during request, stop
            if (state.activeSessionId !== currentSessionId) {
                removePendingMessage(currentSessionId, tempId);
                return;
            }

            if (res.handover && res.direct_session_id) {
                removePendingMessage(currentSessionId, tempId);
                ChatCore.showToast("Percakapan dialihkan langsung ke penjual.");
                await selectSession(res.direct_session_id);
                return;
            }

            removePendingMessage(currentSessionId, tempId);

            if (isAi) {
                // AI replied
                if (res.reply) {
                    // Remove existing "Hubungi Penjual" buttons from earlier AI bubbles
                    if (els.messagesContainer) {
                        els.messagesContainer.querySelectorAll(".chat-bubble-actions").forEach(function (act) {
                            act.remove();
                        });
                    }

                    var aiMsg = {
                        id: res.message_id || ("ai_" + Date.now()),
                        sender_type: "ai",
                        content: res.reply,
                        created_at: new Date().toISOString()
                    };

                    if (els.messagesContainer) {
                        var aiBubbleHtml = createMessageBubbleHtml(aiMsg, true, true);
                        els.messagesContainer.insertAdjacentHTML("beforeend", aiBubbleHtml);
                        bindEscalateButtons();
                    }
                    state.renderedMessages.push(aiMsg);
                    scrollToBottom();
                    updateSessionPreview(currentSessionId, res.reply);
                }
            } else {
                // Direct chat reply from server
                if (res.message) {
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
            }
        } catch (err) {
            hideTypingIndicator();
            removePendingMessage(currentSessionId, tempId);
            if (els.messagesContainer) {
                var failedBubble = els.messagesContainer.querySelector('[data-temp-id="' + tempId + '"]');
                if (failedBubble) {
                    failedBubble.style.opacity = "0.55";
                    failedBubble.title = "Gagal terkirim: " + err.message;
                }
            }
            ChatCore.showToast(err.message || "Gagal mengirim pesan.");
        } finally {
            state.isSending = false;
            if (els.sendBtn) els.sendBtn.disabled = false;
            if (els.messageInput) els.messageInput.focus();
        }
    }

    /**
     * Mengalihkan percakapan aktif dari bot AI ke penjual manusia (Handover/Escalate).
     *
     * Alur:
     * 1. Mengirim permintaan POST ke endpoint `/chat/api/sessions/<id>/escalate-to-seller/`.
     * 2. Backend mematikan flag AI pada sesi atau membuat percakapan tipe 'direct'.
     * 3. Memperbarui UI ke sesi direct yang baru dan memuat ulang pesan secara otomatis.
     *
     * @async
     * @returns {Promise<void>}
     */
    async function escalateToSeller() {
        if (!state.activeSessionId) return;
        try {
            var res = await ChatCore.apiFetch(
                "/chat/api/sessions/" + state.activeSessionId + "/escalate-to-seller/",
                { method: "POST" }
            );
            ChatCore.showToast(res.message || "Terhubung langsung dengan penjual.");
            if (res.direct_session_id) {
                state.activeSessionId = res.direct_session_id;
                await loadSessions(true);
                await selectSession(res.direct_session_id);
            }
        } catch (err) {
            ChatCore.showToast(err.message);
        }
    }

    /**
     * Mengembalikan percakapan penjual langsung ke asisten AI bot toko.
     *
     * Alur:
     * 1. Mengirim permintaan POST ke `/chat/api/sessions/<id>/switch-to-ai/`.
     * 2. Backend mengubah sesi kembali menjadi sesi ber-tipe AI.
     * 3. Memuat ulang daftar sesi dan memilih sesi AI tersebut.
     *
     * @async
     * @returns {Promise<void>}
     */
    async function switchToAiBot() {
        if (!state.activeSessionId) return;
        try {
            var res = await ChatCore.apiFetch(
                "/chat/api/sessions/" + state.activeSessionId + "/switch-to-ai/",
                { method: "POST" }
            );
            ChatCore.showToast(res.message || "Beralih ke Asisten AI.");
            if (res.ai_session_id) {
                state.activeSessionId = res.ai_session_id;
                await loadSessions(true);
                await selectSession(res.ai_session_id);
            }
        } catch (err) {
            ChatCore.showToast(err.message);
        }
    }

    /**
     * Mengubah status arsip (toggle archive/unarchive) sesi percakapan.
     *
     * Alur:
     * 1. Mengirim permintaan POST ke `/chat/api/sessions/<id>/archive/`.
     * 2. Jika sesi yang diarsipkan sedang aktif dibuka, bersihkan sesi aktif.
     * 3. Refresh daftar sesi di sidebar sesuai tab aktif saat ini.
     *
     * @async
     * @param {number|string} [sessionId] - ID sesi yang ingin diarsipkan (default: state.activeSessionId)
     * @returns {Promise<void>}
     */
    async function toggleArchiveSession(sessionId) {
        var targetId = sessionId || state.activeSessionId;
        if (!targetId) return;
        try {
            var res = await ChatCore.apiFetch("/chat/api/sessions/" + targetId + "/archive/", {
                method: "POST"
            });
            ChatCore.showToast(res.is_archived ? "Percakapan diarsipkan." : "Percakapan dikeluarkan dari arsip.");
            if (state.activeSessionId === targetId) {
                state.activeSessionId = null;
            }
            await loadSessions(false);
        } catch (err) {
            ChatCore.showToast(err.message);
        }
    }

    /**
     * Memulai percakapan AI baru dengan toko tertentu atau menyematkan konteks produk ke sesi yang sedang aktif.
     *
     * Alur:
     * - Kasus A (Memilih Toko): Membuat/mengambil sesi AI dengan seller_id yang dipilih dan melampirkan produk (jika ada).
     *   Mengatur tab sidebar ke "Semua", memilih sesi baru, dan menutup modal.
     * - Kasus B (Lampirkan ke Sesi Aktif): Menambahkan produk ke `SessionProductContext` di sesi yang sedang dibuka.
     *
     * @async
     * @param {string|number} sellerId - ID user penjual tujuan (wajib jika membuat sesi baru)
     * @param {string} [productId] - ID produk (integer/UUID/slug produk)
     * @param {string} [productName] - Nama tampilan produk
     * @returns {Promise<void>}
     */
    async function startOrAttachProduct(sellerId, productId, productName) {
        try {
            var productsPayload = [];
            if (productId) {
                productsPayload.push({
                    product_id: productId,
                    product_name: productName || productId
                });
            }

            if (sellerId) {
                state.currentTab = "semua";
                state.searchQuery = "";
                if (els.searchInput) els.searchInput.value = "";
                els.tabButtons.forEach(function (b) {
                    b.classList.toggle("active", b.getAttribute("data-tab") === "semua");
                });

                var res = await ChatCore.apiFetch("/chat/api/sessions/ai/", {
                    method: "POST",
                    body: {
                        seller_id: parseInt(sellerId, 10),
                        products: productsPayload
                    }
                });
                ChatCore.closeModal("productContextModalBackdrop");
                state.activeSessionId = res.session_id;
                await loadSessions(true);
                await selectSession(res.session_id);
                ChatCore.showToast("Sesi chat dengan " + res.seller.store_name + " siap.");
            } else if (state.activeSessionId && productsPayload.length > 0) {
                await ChatCore.apiFetch("/chat/api/sessions/" + state.activeSessionId + "/products/", {
                    method: "POST",
                    body: { products: productsPayload }
                });
                ChatCore.closeModal("productContextModalBackdrop");
                await selectSession(state.activeSessionId);
                ChatCore.showToast("Produk terkait ditambahkan ke percakapan.");
            } else {
                ChatCore.showToast("Pilih toko atau masukkan kode produk.");
            }
        } catch (err) {
            ChatCore.showToast(err.message);
        }
    }

    /**
     * Mengikat seluruh event listener statis di halaman chat pembeli:
     * - Form pencarian dan tombol tab (Semua/Arsip).
     * - Form composer input kirim pesan.
     * - Menu dropdown header (Rating, Laporkan Toko, Eskalasi, dll).
     * - Modal submit Rating dan User Report.
     * - Logika autocomplete pencarian Toko dan Produk.
     *
     * @returns {void}
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
            els.composerForm.addEventListener("submit", handleSendMessage);
        }

        // Header dropdown toggle
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

        // Open Rating Modal (Screen 7)
        var openRatingTriggers = [
            document.getElementById("headerRateBtn"),
            document.getElementById("dropdownRatingBtn")
        ];
        openRatingTriggers.forEach(function (btn) {
            if (!btn) return;
            btn.addEventListener("click", function () {
                if (!state.activeSessionId) {
                    ChatCore.showToast("Pilih percakapan terlebih dahulu untuk memberi rating.");
                    return;
                }
                ChatCore.openModal("ratingModalBackdrop");
            });
        });

        // Submit Rating Form
        var ratingForm = document.getElementById("ratingModalForm");
        if (ratingForm) {
            ratingForm.addEventListener("submit", async function (e) {
                e.preventDefault();
                if (!state.activeSessionId) return;
                var ratingVal = parseInt(document.getElementById("ratingValueInput").value, 10) || 5;
                var feedbackVal = document.getElementById("ratingFeedbackInput").value.trim();
                try {
                    var res = await ChatCore.apiFetch(
                        "/chat/api/sessions/" + state.activeSessionId + "/rating/",
                        {
                            method: "POST",
                            body: { rating: ratingVal, feedback: feedbackVal }
                        }
                    );
                    ChatCore.closeModal("ratingModalBackdrop");
                    ChatCore.showToast(res.message || "Rating berhasil disimpan!");
                } catch (err) {
                    ChatCore.showToast(err.message);
                }
            });
        }

        // Open Report Modal (Screen 8)
        var openReportTriggers = [
            document.getElementById("headerReportBtn"),
            document.getElementById("dropdownReportBtn")
        ];
        openReportTriggers.forEach(function (btn) {
            if (!btn) return;
            btn.addEventListener("click", function () {
                if (!state.activeSessionData || !state.activeSessionData.seller) {
                    ChatCore.showToast("Pilih percakapan terlebih dahulu.");
                    return;
                }
                document.getElementById("reportedUserIdInput").value = state.activeSessionData.seller.id;
                document.getElementById("reportReasonInput").value = "";
                ChatCore.openModal("reportModalBackdrop");
            });
        });

        // Submit Report Form
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
                    ChatCore.showToast(res.message || "Laporan telah dikirim.");
                } catch (err) {
                    ChatCore.showToast(err.message);
                }
            });
        }

        // =====================================================================
        // Search Toko & Produk Terkait (AJAX Debounce + Random Fallback)
        // =====================================================================
        var sellerCache = {
            query: null,
            html: "",
            items: []
        };
        var productCache = {}; // keyed by sellerId + "_" + query

        /**
         * Helper debounce untuk menunda eksekusi fungsi pencarian AJAX saat pengguna mengetik.
         * Mencegah spam request ke server backend pada setiap keystroke.
         *
         * @param {Function} func - Fungsi target yang ingin ditunda eksekusinya
         * @param {number} delay - Waktu tunda dalam milidetik (misal: 250ms)
         * @returns {Function} Fungsi baru yang ter-debounce
         */
        function debounce(func, delay) {
            var timer;
            return function () {
                var context = this, args = arguments;
                clearTimeout(timer);
                timer = setTimeout(function () {
                    func.apply(context, args);
                }, delay);
            };
        }

        /**
         * Membuka dan menampilkan elemen dropdown daftar toko penjual.
         *
         * @returns {void}
         */
        function showSellerDropdown() {
            var listEl = document.getElementById("sellerDropdownList");
            if (listEl) listEl.classList.add("is-open");
        }

        /**
         * Menutup elemen dropdown daftar toko penjual.
         *
         * @returns {void}
         */
        function hideSellerDropdown() {
            var listEl = document.getElementById("sellerDropdownList");
            if (listEl) listEl.classList.remove("is-open");
        }

        /**
         * Membuka dan menampilkan elemen dropdown daftar produk.
         *
         * @returns {void}
         */
        function showProductDropdown() {
            var listEl = document.getElementById("productDropdownList");
            if (listEl) listEl.classList.add("is-open");
        }

        /**
         * Menutup elemen dropdown daftar produk.
         *
         * @returns {void}
         */
        function hideProductDropdown() {
            var listEl = document.getElementById("productDropdownList");
            if (listEl) listEl.classList.remove("is-open");
        }

        /**
         * Mengambil daftar toko penjual via API `/chat/api/sellers/search/?q=...`.
         * Memiliki mekanisme in-memory caching untuk mencegah request berulang jika query sama.
         *
         * Alur:
         * 1. Jika query sama dengan cache dan bukan forceRefresh, gunakan HTML cache.
         * 2. Tampilkan indikator loading jika belum ada item sebelumnya.
         * 3. Ambil data dari server, render avatar, nama toko, email toko.
         * 4. Simpan ke cache dan pasang event listener klik pada tiap item toko.
         *
         * @async
         * @param {string} query - Kata kunci nama toko penjual
         * @param {boolean} [forceRefresh=false] - Paksa ambil data baru tanpa memakai cache
         * @returns {Promise<void>}
         */
        async function fetchSellers(query, forceRefresh) {
            var q = (query || "").trim();
            var itemsEl = document.getElementById("sellerDropdownItems");
            var loadingEl = document.getElementById("sellerDropdownLoading");
            if (!itemsEl) return;

            // Jika ada cache untuk query yang sama, langsung tampilkan tanpa flicker/stutter
            if (!forceRefresh && sellerCache.query === q && sellerCache.html) {
                itemsEl.innerHTML = sellerCache.html;
                bindSellerItemClicks();
                showSellerDropdown();
                return;
            }

            // Jika belum ada item di DOM, tampilkan loading halus
            if (itemsEl.children.length === 0 && loadingEl) {
                loadingEl.hidden = false;
            }
            showSellerDropdown();

            try {
                var url = "/chat/api/sellers/search/?q=" + encodeURIComponent(q);
                var res = await ChatCore.apiFetch(url);
                var sellers = res.sellers || [];

                if (sellers.length === 0) {
                    var emptyHtml = '<li class="chat-search-dropdown-empty">Tidak ada toko yang cocok dengan pencarian.</li>';
                    itemsEl.innerHTML = emptyHtml;
                    sellerCache = { query: q, html: emptyHtml, items: [] };
                } else {
                    var html = "";
                    sellers.forEach(function (s) {
                        html +=
                            '<li class="chat-search-dropdown-item js-select-seller" data-id="' +
                            ChatCore.escapeHtml(String(s.id)) +
                            '" data-name="' +
                            ChatCore.escapeHtml(s.store_name) +
                            '" role="option" tabindex="0">' +
                            '<div class="chat-search-item-avatar">' +
                            ChatCore.escapeHtml(s.initial || "T") +
                            '</div>' +
                            '<div class="chat-search-item-info">' +
                            '<span class="chat-search-item-title">' +
                            ChatCore.escapeHtml(s.store_name) +
                            '</span>' +
                            '<span class="chat-search-item-sub">' +
                            ChatCore.escapeHtml(s.email) +
                            '</span>' +
                            '</div>' +
                            '</li>';
                    });
                    itemsEl.innerHTML = html;
                    sellerCache = { query: q, html: html, items: sellers };
                    bindSellerItemClicks();
                }
            } catch (err) {
                itemsEl.innerHTML = '<li class="chat-search-dropdown-empty">Gagal memuat toko: ' + ChatCore.escapeHtml(err.message) + '</li>';
            } finally {
                if (loadingEl) loadingEl.hidden = true;
            }
        }

        /**
         * Memasang event click dan keyboard (Enter / Space) pada setiap item toko di dalam dropdown.
         *
         * @returns {void}
         */
        function bindSellerItemClicks() {
            var itemsEl = document.getElementById("sellerDropdownItems");
            if (!itemsEl) return;
            itemsEl.querySelectorAll(".js-select-seller").forEach(function (item) {
                item.addEventListener("click", function () {
                    var sid = item.getAttribute("data-id");
                    var sname = item.getAttribute("data-name");
                    selectSeller(sid, sname);
                });
                item.addEventListener("keydown", function (e) {
                    if (e.key === "Enter" || e.key === " ") {
                        e.preventDefault();
                        var sid = item.getAttribute("data-id");
                        var sname = item.getAttribute("data-name");
                        selectSeller(sid, sname);
                    }
                });
            });
        }

        /**
         * Memilih toko penjual dari dropdown:
         * 1. Mengisi input hidden `modalSellerSelect` dan field teks `sellerSearchInput`.
         * 2. Menutup dropdown toko dan mereset pilihan produk sebelumnya.
         * 3. Memunculkan section pilihan produk toko tersebut dan memicu `fetchProducts`.
         *
         * @param {string} sellerId - ID toko/user penjual
         * @param {string} storeName - Nama toko penjual
         * @returns {void}
         */
        function selectSeller(sellerId, storeName) {
            var sellerInput = document.getElementById("sellerSearchInput");
            var sellerHidden = document.getElementById("modalSellerSelect");
            var clearSellerBtn = document.getElementById("clearSellerBtn");
            var productWrap = document.getElementById("productSelectWrap");

            if (sellerHidden) sellerHidden.value = sellerId;
            if (sellerInput) {
                sellerInput.value = storeName;
                sellerInput.setAttribute("data-selected-name", storeName);
            }
            if (clearSellerBtn) clearSellerBtn.hidden = false;
            hideSellerDropdown();

            clearSelectedProduct();

            if (productWrap) {
                productWrap.hidden = false;
            }

            fetchProducts("", sellerId, true);
        }

        /**
         * Mereset pilihan toko penjual, mengosongkan input dan menyembunyikan section pilihan produk.
         *
         * @returns {void}
         */
        function clearSelectedSeller() {
            var sellerInput = document.getElementById("sellerSearchInput");
            var sellerHidden = document.getElementById("modalSellerSelect");
            var clearSellerBtn = document.getElementById("clearSellerBtn");
            var productWrap = document.getElementById("productSelectWrap");

            if (sellerHidden) sellerHidden.value = "";
            if (sellerInput) {
                sellerInput.value = "";
                sellerInput.removeAttribute("data-selected-name");
            }
            if (clearSellerBtn) clearSellerBtn.hidden = true;
            hideSellerDropdown();

            clearSelectedProduct();
            if (productWrap) {
                productWrap.hidden = true;
            }
        }

        /**
         * Mengambil daftar produk milik toko penjual terpilih dari endpoint `/api/products/?seller_id=...&title=...`.
         * Mendukung query pencarian nama produk dan cache per (sellerId + query).
         *
         * @async
         * @param {string} query - Kata kunci judul produk
         * @param {string|number} [sellerId] - ID user penjual pemilik produk
         * @param {boolean} [forceRefresh=false] - Paksa ambil data baru tanpa cache
         * @returns {Promise<void>}
         */
        async function fetchProducts(query, sellerId, forceRefresh) {
            var sId = sellerId || (document.getElementById("modalSellerSelect") ? document.getElementById("modalSellerSelect").value : "");
            if (!sId) return;

            var q = (query || "").trim();
            var cacheKey = sId + "_" + q;
            var itemsEl = document.getElementById("productDropdownItems");
            var loadingEl = document.getElementById("productDropdownLoading");
            if (!itemsEl) return;

            if (!forceRefresh && productCache[cacheKey]) {
                itemsEl.innerHTML = productCache[cacheKey];
                bindProductItemClicks();
                showProductDropdown();
                return;
            }

            if (itemsEl.children.length === 0 && loadingEl) {
                loadingEl.hidden = false;
            }
            showProductDropdown();

            try {
                var url = "/api/products/?seller_id=" + encodeURIComponent(sId) + "&title=" + encodeURIComponent(q);
                var res = await ChatCore.apiFetch(url);
                var products = res.products || res.items || [];

                if (products.length === 0) {
                    var emptyHtml = '<li class="chat-search-dropdown-empty">Belum ada produk dari toko ini atau tidak cocok dengan pencarian.</li>';
                    itemsEl.innerHTML = emptyHtml;
                    productCache[cacheKey] = emptyHtml;
                } else {
                    var html = "";
                    products.forEach(function (p) {
                        var pId = p.product_id || p.id || "";
                        var pName = p.product_name || p.name || pId;
                        var pImg = p.image_url || p.image || null;
                        var pPrice = p.final_price != null ? p.final_price : (p.price != null ? p.price : 0);
                        var priceStr = pPrice ? "Rp " + Number(pPrice).toLocaleString("id-ID") : "";
                        var subText = [priceStr, pId ? "ID: " + pId : ""].filter(Boolean).join(" • ");
                        html +=
                            '<li class="chat-search-dropdown-item js-select-product" data-id="' +
                            ChatCore.escapeHtml(pId) +
                            '" data-name="' +
                            ChatCore.escapeHtml(pName) +
                            '" role="option" tabindex="0">' +
                            '<div class="chat-search-item-img">' +
                            (pImg ? '<img src="' + ChatCore.escapeHtml(pImg) + '" alt="" style="width:100%;height:100%;object-fit:cover;border-radius:4px;">' : '📦') +
                            '</div>' +
                            '<div class="chat-search-item-info">' +
                            '<span class="chat-search-item-title">' +
                            ChatCore.escapeHtml(pName) +
                            '</span>' +
                            '<span class="chat-search-item-sub">' +
                            ChatCore.escapeHtml(subText) +
                            '</span>' +
                            '</div>' +
                            '</li>';
                    });
                    itemsEl.innerHTML = html;
                    productCache[cacheKey] = html;
                    bindProductItemClicks();
                }
            } catch (err) {
                itemsEl.innerHTML = '<li class="chat-search-dropdown-empty">Gagal memuat produk: ' + ChatCore.escapeHtml(err.message) + '</li>';
            } finally {
                if (loadingEl) loadingEl.hidden = true;
            }
        }

        /**
         * Memasang event click dan keyboard pada setiap item produk dalam dropdown.
         *
         * @returns {void}
         */
        function bindProductItemClicks() {
            var itemsEl = document.getElementById("productDropdownItems");
            if (!itemsEl) return;
            itemsEl.querySelectorAll(".js-select-product").forEach(function (item) {
                item.addEventListener("click", function () {
                    var pid = item.getAttribute("data-id");
                    var pname = item.getAttribute("data-name");
                    selectProduct(pid, pname);
                });
                item.addEventListener("keydown", function (e) {
                    if (e.key === "Enter" || e.key === " ") {
                        e.preventDefault();
                        var pid = item.getAttribute("data-id");
                        var pname = item.getAttribute("data-name");
                        selectProduct(pid, pname);
                    }
                });
            });
        }

        /**
         * Memilih produk dari dropdown:
         * 1. Mengisi ID dan Nama produk pada input hidden form modal.
         * 2. Menutup dropdown dan menampilkan chip info produk terpilih.
         *
         * @param {string} productId - ID/Kode produk
         * @param {string} productName - Nama lengkap produk
         * @returns {void}
         */
        function selectProduct(productId, productName) {
            var productInput = document.getElementById("productSearchInput");
            var productIdHidden = document.getElementById("modalProductIdInput");
            var productNameHidden = document.getElementById("modalProductNameInput");
            var clearProductBtn = document.getElementById("clearProductBtn");
            var chipEl = document.getElementById("selectedProductChip");
            var chipText = document.getElementById("selectedProductNameText");

            if (productIdHidden) productIdHidden.value = productId;
            if (productNameHidden) productNameHidden.value = productName;
            if (productInput) productInput.value = productName;
            if (clearProductBtn) clearProductBtn.hidden = false;
            hideProductDropdown();

            if (chipEl && chipText) {
                chipText.textContent = productName + " (" + productId + ")";
                chipEl.hidden = true;
            }
        }

        /**
         * Mereset pilihan produk pada modal, mengosongkan input dan menyembunyikan chip produk.
         *
         * @returns {void}
         */
        function clearSelectedProduct() {
            var productInput = document.getElementById("productSearchInput");
            var productIdHidden = document.getElementById("modalProductIdInput");
            var productNameHidden = document.getElementById("modalProductNameInput");
            var clearProductBtn = document.getElementById("clearProductBtn");
            var chipEl = document.getElementById("selectedProductChip");

            if (productIdHidden) productIdHidden.value = "";
            if (productNameHidden) productNameHidden.value = "";
            if (productInput) productInput.value = "";
            if (clearProductBtn) clearProductBtn.hidden = true;
            hideProductDropdown();
            if (chipEl) chipEl.hidden = true;
        }

        var debouncedFetchSellers = debounce(function (val) {
            fetchSellers(val, false);
        }, 250);

        var debouncedFetchProducts = debounce(function (val) {
            var sellerId = document.getElementById("modalSellerSelect") ? document.getElementById("modalSellerSelect").value : "";
            fetchProducts(val, sellerId, false);
        }, 250);

        var sellerSearchInput = document.getElementById("sellerSearchInput");
        if (sellerSearchInput) {
            sellerSearchInput.addEventListener("focus", function () {
                hideProductDropdown();
                fetchSellers(sellerSearchInput.value.trim(), false);
            });

            sellerSearchInput.addEventListener("input", function () {
                var val = sellerSearchInput.value.trim();
                var clearBtn = document.getElementById("clearSellerBtn");
                if (clearBtn) clearBtn.hidden = !val;

                var sellerHidden = document.getElementById("modalSellerSelect");
                var selectedName = sellerSearchInput.getAttribute("data-selected-name");
                if (sellerHidden && sellerHidden.value && val !== selectedName) {
                    sellerHidden.value = "";
                    var productWrap = document.getElementById("productSelectWrap");
                    if (productWrap) productWrap.hidden = true;
                    clearSelectedProduct();
                }

                debouncedFetchSellers(val);
            });
        }

        var clearSellerBtn = document.getElementById("clearSellerBtn");
        if (clearSellerBtn) {
            clearSellerBtn.addEventListener("click", function () {
                clearSelectedSeller();
                if (sellerSearchInput) {
                    sellerSearchInput.focus();
                    fetchSellers("", true);
                }
            });
        }

        var productSearchInput = document.getElementById("productSearchInput");
        if (productSearchInput) {
            productSearchInput.addEventListener("focus", function () {
                hideSellerDropdown();
                var sellerId = document.getElementById("modalSellerSelect") ? document.getElementById("modalSellerSelect").value : "";
                if (sellerId) {
                    fetchProducts(productSearchInput.value.trim(), sellerId, false);
                }
            });

            productSearchInput.addEventListener("input", function () {
                var val = productSearchInput.value.trim();
                var clearBtn = document.getElementById("clearProductBtn");
                if (clearBtn) clearBtn.hidden = !val;

                var productIdHidden = document.getElementById("modalProductIdInput");
                if (productIdHidden) productIdHidden.value = "";
                var productNameHidden = document.getElementById("modalProductNameInput");
                if (productNameHidden) productNameHidden.value = "";
                var chipEl = document.getElementById("selectedProductChip");
                if (chipEl) chipEl.hidden = true;

                debouncedFetchProducts(val);
            });
        }

        var clearProductBtn = document.getElementById("clearProductBtn");
        if (clearProductBtn) {
            clearProductBtn.addEventListener("click", function () {
                clearSelectedProduct();
                if (productSearchInput) {
                    productSearchInput.focus();
                    var sellerId = document.getElementById("modalSellerSelect") ? document.getElementById("modalSellerSelect").value : "";
                    fetchProducts("", sellerId, true);
                }
            });
        }

        var removeChipBtn = document.getElementById("removeSelectedProductBtn");
        if (removeChipBtn) {
            removeChipBtn.addEventListener("click", function () {
                clearSelectedProduct();
            });
        }

        // Tutup dropdown saat klik di luar area
        document.addEventListener("click", function (e) {
            var sellerWrap = document.getElementById("sellerSelectWrap");
            if (sellerWrap && !sellerWrap.contains(e.target)) {
                hideSellerDropdown();
            }

            var productWrap = document.getElementById("productSelectWrap");
            if (productWrap && !productWrap.contains(e.target)) {
                hideProductDropdown();
            }
        });

        // Trigger buka modal produk & toko
        var productModalTriggers = [
            document.getElementById("openNewChatBtn"),
            document.getElementById("composerPlusBtn"),
            document.getElementById("dropdownAddProductBtn"),
            document.getElementById("addContextInlineBtn"),
            document.getElementById("emptyStateStartChatBtn")
        ];
        productModalTriggers.forEach(function (btn) {
            if (!btn) return;
            btn.addEventListener("click", function () {
                var isAttachToActive = (btn.id === "dropdownAddProductBtn" || btn.id === "addContextInlineBtn") &&
                                       state.activeSessionData && state.activeSessionData.seller;

                if (isAttachToActive) {
                    var s = state.activeSessionData.seller;
                    selectSeller(String(s.id), s.store_name);
                    setTimeout(function () {
                        var pInput = document.getElementById("productSearchInput");
                        if (pInput) pInput.focus();
                    }, 120);
                } else {
                    clearSelectedSeller();
                    // Pre-fetch random toko segera di latar belakang agar siap ketika input diklik
                    fetchSellers("", true);
                    setTimeout(function () {
                        var sInput = document.getElementById("sellerSearchInput");
                        if (sInput) {
                            sInput.focus();
                        }
                    }, 120);
                }

                ChatCore.openModal("productContextModalBackdrop");
            });
        });

        var productModalForm = document.getElementById("productContextModalForm");
        if (productModalForm) {
            productModalForm.addEventListener("submit", function (e) {
                e.preventDefault();
                var sellerId = document.getElementById("modalSellerSelect") ? document.getElementById("modalSellerSelect").value : "";
                var productId = document.getElementById("modalProductIdInput") ? document.getElementById("modalProductIdInput").value.trim() : "";
                var productName = document.getElementById("modalProductNameInput") ? document.getElementById("modalProductNameInput").value.trim() : "";

                if (!sellerId && !state.activeSessionId) {
                    ChatCore.showToast("Silakan pilih toko penjual terlebih dahulu.");
                    return;
                }
                startOrAttachProduct(sellerId, productId, productName);
            });
        }

        var dropdownEscalate = document.getElementById("dropdownEscalateBtn");
        if (dropdownEscalate) {
            dropdownEscalate.addEventListener("click", function () {
                escalateToSeller();
            });
        }

        var dropdownSwitchAi = document.getElementById("dropdownSwitchAiBtn");
        if (dropdownSwitchAi) {
            dropdownSwitchAi.addEventListener("click", function () {
                switchToAiBot();
            });
        }

        var dropdownArchive = document.getElementById("dropdownArchiveBtn");
        if (dropdownArchive) {
            dropdownArchive.addEventListener("click", function () {
                toggleArchiveSession(state.activeSessionId);
            });
        }
    }

    /**
     * Entry point inisialisasi modul chat pembeli saat DOM selesai dimuat:
     * 1. Cache elemen DOM penting (`cacheElements`).
     * 2. Ikat event handler UI (`bindEvents`).
     * 3. Periksa URL/konfigurasi `window.CHAT_INITIAL_CONFIG`: jika ada sellerId awal (misal dari tombol "Chat Penjual" di katalog),
     *    langsung mulai/lampirkan sesi chat dengan toko tersebut. Jika tidak, muat daftar sesi pembeli.
     * 4. Memulai polling interval periodik (setiap 6 detik) untuk memantau pesan baru secara halus (anti-flicker).
     *
     * @async
     * @returns {Promise<void>}
     */
    async function init() {
        cacheElements();
        bindEvents();

        var cfg = window.CHAT_INITIAL_CONFIG || {};
        if (cfg.initialSellerId) {
            await startOrAttachProduct(cfg.initialSellerId, cfg.initialProductId, cfg.initialProductName);
        } else {
            await loadSessions(false);
        }

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


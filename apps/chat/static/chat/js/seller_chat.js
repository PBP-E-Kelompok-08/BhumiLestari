(function () {
    "use strict";

    var state = {
        currentTab: "semua",
        searchQuery: "",
        sessions: [],
        activeSessionId: null,
        activeSessionData: null,
        pollingTimer: null
    };

    var els = {};

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
        els.contextBar = document.getElementById("sellerProductContextBar");
        els.contextTags = document.getElementById("sellerProductContextTags");
        els.headerMenuBtn = document.getElementById("sellerHeaderMenuBtn");
        els.headerDropdown = document.getElementById("sellerHeaderDropdownMenu");
        els.shell = document.getElementById("chatShell");
    }

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

    function highlightActiveSessionItem() {
        if (!els.sessionList) return;
        els.sessionList.querySelectorAll(".chat-session-item").forEach(function (item) {
            item.classList.toggle("active", item.getAttribute("data-session-id") === state.activeSessionId);
        });
    }

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

    function renderMessages(messages, session) {
        if (!els.messagesContainer) return;
        if (!messages || messages.length === 0) {
            els.messagesContainer.innerHTML =
                '<div class="chat-state-box">' +
                '<h2 class="chat-state-title">Belum Ada Pesan</h2>' +
                '<p class="chat-state-desc">Kirim pesan balasan untuk menyapa pembeli ini.</p>' +
                "</div>";
            return;
        }

        var html = "";
        messages.forEach(function (m) {
            var timeStr = ChatCore.formatTimeHM(m.created_at);

            if (m.sender_type === "system") {
                html +=
                    '<div class="chat-bubble-row system">' +
                    '<div class="chat-bubble">' +
                    ChatCore.escapeHtml(m.content) +
                    "</div>" +
                    "</div>";
                return;
            }

            // In Seller POV (Screen 2):
            // Buyer messages are on the left (incoming, white bubble)
            // Seller / AI messages are on the right (outgoing, dark green bubble)
            var isIncomingBuyer = m.sender_type === "buyer";
            var rowClass = isIncomingBuyer ? "incoming" : "outgoing";

            html += '<div class="chat-bubble-row ' + rowClass + '">';
            html += '<div class="chat-bubble">';

            if (m.sender_type === "ai") {
                html +=
                    '<span class="chat-bot-sender-name" style="color: #F2EAC0;">Balasan Bot Otomatis</span>';
            }

            html += ChatCore.escapeHtml(m.content);

            html += "</div>";
            if (timeStr) {
                html += '<span class="chat-bubble-time">' + ChatCore.escapeHtml(timeStr) + "</span>";
            }
            html += "</div>";
        });

        els.messagesContainer.innerHTML = html;

        if (els.chatBody) {
            els.chatBody.scrollTop = els.chatBody.scrollHeight;
        }
    }

    function openReportBuyerModal() {
        if (!state.activeSessionData || !state.activeSessionData.buyer) {
            ChatCore.showToast("Pilih percakapan pembeli terlebih dahulu.");
            return;
        }
        document.getElementById("reportedUserIdInput").value = state.activeSessionData.buyer.id;
        document.getElementById("reportReasonInput").value = "";
        ChatCore.openModal("reportModalBackdrop");
    }

    async function handleSendDirectReply(e) {
        e.preventDefault();
        if (!els.messageInput) return;
        var text = els.messageInput.value.trim();
        if (!text) return;

        if (!state.activeSessionId) {
            ChatCore.showToast("Pilih percakapan pembeli terlebih dahulu.");
            return;
        }

        els.messageInput.value = "";
        try {
            await ChatCore.apiFetch("/chat/api/sessions/" + state.activeSessionId + "/direct-send/", {
                method: "POST",
                body: { content: text }
            });
            await selectSession(state.activeSessionId);
        } catch (err) {
            ChatCore.showToast(err.message);
        }
    }

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

    async function init() {
        cacheElements();
        bindEvents();
        await loadSessions(false);

        state.pollingTimer = setInterval(function () {
            if (state.activeSessionId) {
                ChatCore.apiFetch("/chat/api/sessions/" + state.activeSessionId + "/messages/")
                    .then(function (data) {
                        state.activeSessionData = data.session;
                        renderMessages(data.messages || [], data.session);
                    })
                    .catch(function () {});
            }
        }, 6000);
    }

    document.addEventListener("DOMContentLoaded", init);
})();


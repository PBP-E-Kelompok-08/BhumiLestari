(function () {
    "use strict";

    var state = {
        currentTab: "semua",
        channels: [],
        myChannel: null,
        otherChannels: [],
        searchQuery: "",
        activeChannelId: null,
        activeChannelData: null,
        isSending: false
    };

    var els = {};

    /**
     * Melakukan caching referensi elemen DOM pada layar Saluran Siaran (Broadcast Channel).
     * Mengatur status awal form composer siaran: disembunyikan sampai hak akses pemilik diverifikasi.
     */
    function cacheElements() {
        els.channelList = document.getElementById("broadcastChannelList");
        els.searchForm = document.getElementById("broadcastSearchForm");
        els.searchInput = document.getElementById("broadcastSearchInput");
        els.tabButtons = document.querySelectorAll(".chat-tab-pill");
        els.channelTitle = document.getElementById("activeChannelTitle");
        els.channelFollowers = document.getElementById("activeChannelFollowers");
        els.messagesContainer = document.getElementById("broadcastMessagesContainer");
        els.mainBody = document.getElementById("broadcastMainBody");
        els.readonlyFooter = document.getElementById("broadcastReadonlyFooter");
        els.composerFooter = document.getElementById("broadcastComposerFooter");
        els.composerForm = document.getElementById("broadcastComposerForm");
        els.messageInput = document.getElementById("broadcastMessageInput");
        els.sendBtn = document.getElementById("broadcastSendBtn");
        els.headerMenuBtn = document.getElementById("broadcastHeaderMenuBtn");
        els.headerDropdown = document.getElementById("broadcastHeaderDropdownMenu");
        els.dropdownArchiveBtn = document.getElementById("broadcastDropdownArchiveBtn");
        els.shell = document.getElementById("chatShell");

        if (els.composerFooter) {
            els.composerFooter.style.display = "none";
            els.composerFooter.hidden = true;
        }
        if (els.readonlyFooter) {
            els.readonlyFooter.style.display = "flex";
            els.readonlyFooter.hidden = false;
        }
    }

    /**
     * DISABLED
     * Memformat angka jumlah pengikut saluran menjadi format ringkas (misal: "1.5k followers").
     * @param {number|string} num - Jumlah total pengikut saluran.
     * @returns {string} String label pengikut yang rapi.
     */
    function formatFollowerCount(num) {
        var n = parseInt(num, 10) || 0;
        if (n >= 1000) {
            return (n / 1000).toFixed(n % 1000 === 0 ? 0 : 1) + "k followers";
        }
        return n + " followers";
    }

    /**
     * Mengambil daftar saluran siaran toko dari endpoint `/chat/api/broadcast/channels/`.
     * Mendukung pemfilteran tab (semua/arsip) dan query pencarian nama saluran toko.
     * @param {boolean} preserveSelection - Jika true, tidak mengubah saluran aktif saat ini.
     */
    async function loadChannels(preserveSelection) {
        try {
            var url = "/chat/api/broadcast/channels/?tab=" + encodeURIComponent(state.currentTab);
            if (state.searchQuery) {
                url += "&search=" + encodeURIComponent(state.searchQuery);
            }
            var data = await ChatCore.apiFetch(url);
            state.channels = data.channels || [];
            state.myChannel = data.my_channel || null;
            state.otherChannels = data.other_channels || [];
            renderChannelList();

            if (!preserveSelection && state.channels.length > 0 && !state.activeChannelId) {
                selectChannel(state.myChannel ? state.myChannel.id : state.channels[0].id);
            } else if (state.activeChannelId) {
                highlightActiveChannelItem();
            }
        } catch (err) {
            if (els.channelList) {
                els.channelList.innerHTML =
                    '<li class="chat-sidebar-empty">Gagal memuat channel: ' +
                    ChatCore.escapeHtml(err.message) +
                    "</li>";
            }
        }
    }

    /**
     * Membangun markup HTML untuk satu item saluran siaran di daftar sidebar.
     * Menyertakan lencana "Saluran Anda" jika saluran tersebut adalah milik penjual yang sedang login.
     * @param {object} c - Objek data saluran siaran.
     * @param {boolean} isMyChannel - True jika saluran ini dimiliki oleh penjual yang aktif.
     * @returns {string} Markup HTML elemen <li> saluran siaran.
     */
    function renderChannelItemHtml(c, isMyChannel) {
        var isActive = c.id === state.activeChannelId;
        var preview =
            (c.last_message && c.last_message.content) ||
            c.description ||
            "Selamat datang di channel resmi toko!";
        preview = preview.replace(/\s+/g, " ").trim();

        var ownerBadge = isMyChannel
            ? ' <span class="chat-broadcast-owner-badge">Saluran Anda</span>'
            : '';

        return (
            '<li class="chat-session-item ' +
            (isActive ? "active" : "") +
            (isMyChannel ? " my-channel-item" : "") +
            '" data-channel-id="' +
            c.id +
            '" tabindex="0" role="button" aria-label="Buka ' +
            ChatCore.escapeHtml(c.name) +
            '">' +
            ChatCore.getAvatarSvgHtml() +
            '<div class="chat-session-info">' +
            '<h3 class="chat-session-title">' +
            ChatCore.escapeHtml(c.name) +
            ownerBadge +
            "</h3>" +
            '<p class="chat-session-preview">' +
            ChatCore.escapeHtml(preview) +
            "</p>" +
            "</div>" +
            '<div class="chat-session-meta">' +
            '<button type="button" class="chat-archive-item-btn js-archive-channel" data-channel-id="' +
            c.id +
            '" title="' +
            (c.is_archived ? "Buka Arsip Channel" : "Arsipkan Channel") +
            '" aria-label="Arsipkan Channel">' +
            ChatCore.getArchiveIconSvgHtml() +
            "</button>" +
            "</div>" +
            "</li>"
        );
    }

    /**
     * Merender daftar saluran siaran ke sidebar (#broadcastChannelList).
     * Memisahkan bagian "Saluran Toko Anda" di bagian paling atas
     * dan "Saluran Toko Lainnya" di bawah pembatas.
     */
    function renderChannelList() {
        if (!els.channelList) return;
        if (state.channels.length === 0) {
            els.channelList.innerHTML =
                '<li class="chat-sidebar-empty">Tidak ada channel broadcast pada tab ini.</li>';
            return;
        }

        var html = "";

        if (state.myChannel) {
            html += '<li class="chat-broadcast-section-header">Saluran Toko Anda</li>';
            html += renderChannelItemHtml(state.myChannel, true);

            if (state.otherChannels && state.otherChannels.length > 0) {
                html += '<li class="chat-broadcast-section-separator" role="separator"></li>';
                html += '<li class="chat-broadcast-section-header">Saluran Toko Lainnya</li>';
                state.otherChannels.forEach(function (c) {
                    html += renderChannelItemHtml(c, false);
                });
            }
        } else {
            state.channels.forEach(function (c) {
                html += renderChannelItemHtml(c, false);
            });
        }

        els.channelList.innerHTML = html;
        bindChannelListEvents();
    }

    /**
     * Mengikat pendengar klik dan keyboard (Enter/Space) pada setiap item saluran di sidebar,
     * serta tombol arsip saluran siaran.
     */
    function bindChannelListEvents() {
        if (!els.channelList) return;

        els.channelList.querySelectorAll(".chat-session-item").forEach(function (item) {
            item.addEventListener("click", function (e) {
                if (e.target.closest(".js-archive-channel")) return;
                var cid = parseInt(item.getAttribute("data-channel-id"), 10);
                selectChannel(cid);
                if (els.shell) els.shell.classList.add("mobile-thread-active");
            });
            item.addEventListener("keydown", function (e) {
                if (e.key === "Enter" || e.key === " ") {
                    e.preventDefault();
                    var cid = parseInt(item.getAttribute("data-channel-id"), 10);
                    selectChannel(cid);
                }
            });
        });

        els.channelList.querySelectorAll(".js-archive-channel").forEach(function (btn) {
            btn.addEventListener("click", function (e) {
                e.stopPropagation();
                var cid = parseInt(btn.getAttribute("data-channel-id"), 10);
                toggleArchiveChannel(cid);
            });
        });
    }

    /**
     * Menandai item saluran yang aktif di sidebar dengan menambahkan kelas CSS `.active`.
     */
    function highlightActiveChannelItem() {
        if (!els.channelList) return;
        els.channelList.querySelectorAll(".chat-session-item").forEach(function (item) {
            var cid = parseInt(item.getAttribute("data-channel-id"), 10);
            item.classList.toggle("active", cid === state.activeChannelId);
        });
    }

    /**
     * Memilih saluran siaran tertentu:
     * 1. Mengambil riwayat pesan siaran dari `/chat/api/broadcast/channels/<id>/messages/`.
     * 2. Menyesuaikan header (nama channel & jumlah pengikut).
     * 3. Mengecek apakah pengguna saat ini adalah pemilik saluran (`is_owner`).
     *    - Jika pemilik: Menampilkan form penulisan siaran (#broadcastComposerFooter).
     *    - Jika bukan: Menampilkan footer read-only (#broadcastReadonlyFooter).
     * 4. Merender daftar pesan siaran.
     * @param {number} channelId - ID numerik BroadcastChannel yang dipilih.
     */
    async function selectChannel(channelId) {
        if (!channelId) return;
        state.activeChannelId = channelId;
        highlightActiveChannelItem();

        try {
            var data = await ChatCore.apiFetch(
                "/chat/api/broadcast/channels/" + channelId + "/messages/"
            );
            state.activeChannelData = data.channel;

            if (els.channelTitle) els.channelTitle.textContent = data.channel.name;
            if (els.channelFollowers) {
                els.channelFollowers.textContent = formatFollowerCount(data.channel.followers_count);
            }

            var isOwner = Boolean(data.channel && data.channel.is_owner);
            if (els.readonlyFooter && els.composerFooter) {
                if (isOwner) {
                    els.readonlyFooter.style.display = "none";
                    els.readonlyFooter.hidden = true;
                    els.composerFooter.style.display = "flex";
                    els.composerFooter.hidden = false;
                    if (els.messageInput) {
                        els.messageInput.placeholder = "Ketik pesan siaran untuk pengikut tokomu...";
                    }
                } else {
                    els.composerFooter.style.display = "none";
                    els.composerFooter.hidden = true;
                    els.readonlyFooter.style.display = "flex";
                    els.readonlyFooter.hidden = false;
                }
            }

            renderBroadcastMessages(data.messages || [], isOwner);
        } catch (err) {
            ChatCore.showToast(err.message);
        }
    }

    /**
     * Mengarsipkan atau membatalkan pengarsipan saluran siaran via POST `/chat/api/broadcast/channels/<id>/archive/`.
     * @param {number} channelId - ID saluran siaran yang akan diarsipkan.
     */
    async function toggleArchiveChannel(channelId) {
        var targetId = channelId || state.activeChannelId;
        if (!targetId) return;
        try {
            var res = await ChatCore.apiFetch(
                "/chat/api/broadcast/channels/" + targetId + "/archive/",
                { method: "POST" }
            );
            ChatCore.showToast(
                res.is_archived ? "Channel siaran diarsipkan." : "Channel siaran dikeluarkan dari arsip."
            );
            if (state.activeChannelId === targetId) {
                state.activeChannelId = null;
            }
            await loadChannels(false);
        } catch (err) {
            ChatCore.showToast(err.message);
        }
    }

    /**
     * Merender seluruh daftar pesan pengumuman siaran ke dalam kontainer pesan.
     * Mengurutkan pesan secara kronologis (pesan terlama di atas, terbaru di bawah)
     * dan menggulung scroll ke bagian terbawah.
     * @param {Array} messages - Daftar pesan siaran dari backend.
     * @param {boolean} isOwner - Status apakah pengguna adalah pemilik saluran.
     */
    function renderBroadcastMessages(messages, isOwner) {
        if (!els.messagesContainer) return;
        if (!messages || messages.length === 0) {
            els.messagesContainer.innerHTML =
                '<div class="chat-state-box">' +
                '<h2 class="chat-state-title">Belum Ada Pengumuman</h2>' +
                '<p class="chat-state-desc">' +
                (isOwner
                    ? "Kirim pesan siaran pertama Anda untuk semua pengikut channel."
                    : "Toko ini belum mengirimkan pengumuman siaran.") +
                "</p>" +
                "</div>";
            return;
        }

        // Messages come ordered newest first from model Meta; display chronologically top-to-bottom
        var chronological = messages.slice().reverse();
        var html = "";

        chronological.forEach(function (m) {
            var timeStr = ChatCore.formatTimeHM(m.created_at);
            var rowClass = isOwner ? "outgoing" : "incoming";

            html += '<div class="chat-bubble-row ' + rowClass + '">';
            html += '<div class="chat-bubble">' + ChatCore.escapeHtml(m.content) + "</div>";

            if (timeStr) {
                html += '<span class="chat-bubble-time">' + ChatCore.escapeHtml(timeStr) + "</span>";
            }
            html += "</div>";
        });

        els.messagesContainer.innerHTML = html;

        if (els.mainBody) {
            els.mainBody.scrollTop = els.mainBody.scrollHeight;
        }
    }

    /**
     * Menambahkan satu gelembung pesan siaran baru secara instan di akhir percakapan (Optimistic UI).
     * @param {object} m - Objek pesan siaran (id/temp_id, content, created_at).
     * @param {boolean} isOwner - True jika pesan dikirim oleh pemilik toko.
     */
    function appendBroadcastMessage(m, isOwner) {
        if (!els.messagesContainer) return;
        var emptyBox = els.messagesContainer.querySelector(".chat-state-box");
        if (emptyBox) {
            els.messagesContainer.innerHTML = "";
        }

        var timeStr = ChatCore.formatTimeHM(m.created_at);
        var rowClass = isOwner ? "outgoing" : "incoming";
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
        html += '<div class="chat-bubble">' + ChatCore.escapeHtml(m.content) + "</div>";

        if (timeStr) {
            html += '<span class="chat-bubble-time">' + ChatCore.escapeHtml(timeStr) + "</span>";
        }
        html += "</div>";

        els.messagesContainer.insertAdjacentHTML("beforeend", html);
        if (els.mainBody) {
            els.mainBody.scrollTop = els.mainBody.scrollHeight;
        }
    }

    /**
     * Memperbarui cuplikan pesan terakhir (preview) pada item saluran di sidebar
     * seketika setelah pesan siaran baru dikirim.
     * @param {number} channelId - ID saluran siaran.
     * @param {string} content - Teks pesan siaran baru.
     */
    function updateChannelLastMessage(channelId, content) {
        var ch = state.channels.find(function (c) { return c.id === channelId; });
        if (ch) {
            ch.last_message = { content: content, created_at: new Date().toISOString() };
        }
        if (state.myChannel && state.myChannel.id === channelId) {
            state.myChannel.last_message = { content: content, created_at: new Date().toISOString() };
        }
        renderChannelList();
    }

    /**
     * Mengikat seluruh event listener interaktif pada antarmuka saluran siaran:
     * - Form pencarian saluran toko.
     * - Tombol tab filter (Semua / Arsip).
     * - Dropdown menu header dan tombol arsip.
     * - Form pengiriman pesan siaran baru pemilik toko (optimistic send & rekonsiliasi ID).
     */
    function bindEvents() {
        if (els.searchForm) {
            els.searchForm.addEventListener("submit", function (e) {
                e.preventDefault();
                state.searchQuery = els.searchInput ? els.searchInput.value.trim() : "";
                loadChannels(true);
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
                state.activeChannelId = null;
                loadChannels(false);
            });
        });

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

        if (els.dropdownArchiveBtn) {
            els.dropdownArchiveBtn.addEventListener("click", function () {
                toggleArchiveChannel(state.activeChannelId);
            });
        }

        // Active chat composer form submission for broadcast channel owner
        if (els.composerForm) {
            els.composerForm.addEventListener("submit", async function (e) {
                e.preventDefault();
                if (!state.activeChannelId) return;
                if (!els.messageInput) return;
                if (state.isSending) return;

                var content = els.messageInput.value.trim();
                if (!content) return;

                var channelId = state.activeChannelId;
                var tempId = "temp_" + Date.now() + "_" + Math.floor(Math.random() * 1000000);

                // 1. Instantly clear input & prevent double-submit
                els.messageInput.value = "";
                state.isSending = true;
                if (els.sendBtn) els.sendBtn.disabled = true;

                // 2. Instantly append optimistic broadcast bubble
                var optMsg = {
                    id: tempId,
                    temp_id: tempId,
                    content: content,
                    created_at: new Date().toISOString(),
                    is_pending: true
                };
                appendBroadcastMessage(optMsg, true);
                updateChannelLastMessage(channelId, content);

                try {
                    var res = await ChatCore.apiFetch(
                        "/chat/api/broadcast/channels/" + channelId + "/send/",
                        {
                            method: "POST",
                            body: { content: content }
                        }
                    );

                    var optBubble = els.messagesContainer.querySelector('[data-temp-id="' + tempId + '"]');
                    if (optBubble && res.message) {
                        optBubble.setAttribute("data-msg-id", res.message.id);
                        optBubble.removeAttribute("data-temp-id");
                        optBubble.classList.remove("pending-send");
                        var timeEl = optBubble.querySelector(".chat-bubble-time");
                        if (timeEl && res.message.created_at) {
                            timeEl.textContent = ChatCore.formatTimeHM(res.message.created_at);
                        }
                    }
                    ChatCore.showToast("Pesan siaran berhasil dikirim!");
                } catch (err) {
                    var optBubble = els.messagesContainer.querySelector('[data-temp-id="' + tempId + '"]');
                    if (optBubble) {
                        optBubble.style.opacity = "0.55";
                        optBubble.title = "Gagal terkirim: " + err.message;
                    }
                    ChatCore.showToast(err.message || "Gagal mengirim pesan siaran.");
                } finally {
                    state.isSending = false;
                    if (els.sendBtn) els.sendBtn.disabled = false;
                    if (els.messageInput) els.messageInput.focus();
                }
            });
        }
    }

    document.addEventListener("DOMContentLoaded", function () {
        cacheElements();
        bindEvents();
        loadChannels(false);
    });
})();

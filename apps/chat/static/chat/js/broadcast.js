(function () {
    "use strict";

    var state = {
        currentTab: "semua",
        channels: [],
        searchQuery: "",
        activeChannelId: null,
        activeChannelData: null
    };

    var els = {};

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
        els.headerMenuBtn = document.getElementById("broadcastHeaderMenuBtn");
        els.headerDropdown = document.getElementById("broadcastHeaderDropdownMenu");
        els.dropdownArchiveBtn = document.getElementById("broadcastDropdownArchiveBtn");
        els.shell = document.getElementById("chatShell");
    }

    function formatFollowerCount(num) {
        var n = parseInt(num, 10) || 0;
        if (n >= 1000) {
            return (n / 1000).toFixed(n % 1000 === 0 ? 0 : 1) + "k followers";
        }
        return n + " followers";
    }

    async function loadChannels(preserveSelection) {
        try {
            var url = "/chat/api/broadcast/channels/?tab=" + encodeURIComponent(state.currentTab);
            if (state.searchQuery) {
                url += "&search=" + encodeURIComponent(state.searchQuery);
            }
            var data = await ChatCore.apiFetch(url);
            state.channels = data.channels || [];
            renderChannelList();

            if (!preserveSelection && state.channels.length > 0 && !state.activeChannelId) {
                selectChannel(state.channels[0].id);
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

    function renderChannelList() {
        if (!els.channelList) return;
        if (state.channels.length === 0) {
            els.channelList.innerHTML =
                '<li class="chat-sidebar-empty">Tidak ada channel broadcast pada tab ini.</li>';
            return;
        }

        var html = "";
        state.channels.forEach(function (c) {
            var isActive = c.id === state.activeChannelId;
            var preview =
                (c.last_message && c.last_message.content) ||
                c.description ||
                "Selamat datang di channel resmi toko!";
            preview = preview.replace(/\s+/g, " ").trim();

            html +=
                '<li class="chat-session-item ' +
                (isActive ? "active" : "") +
                '" data-channel-id="' +
                c.id +
                '" tabindex="0" role="button" aria-label="Buka ' +
                ChatCore.escapeHtml(c.name) +
                '">' +
                ChatCore.getAvatarSvgHtml() +
                '<div class="chat-session-info">' +
                '<h3 class="chat-session-title">' +
                ChatCore.escapeHtml(c.name) +
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
                "</li>";
        });

        els.channelList.innerHTML = html;

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

    function highlightActiveChannelItem() {
        if (!els.channelList) return;
        els.channelList.querySelectorAll(".chat-session-item").forEach(function (item) {
            var cid = parseInt(item.getAttribute("data-channel-id"), 10);
            item.classList.toggle("active", cid === state.activeChannelId);
        });
    }

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

            renderBroadcastMessages(data.messages || [], Boolean(data.channel.is_owner));
        } catch (err) {
            ChatCore.showToast(err.message);
        }
    }

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

            if (isOwner) {
                html +=
                    '<div class="chat-broadcast-meta-row">' +
                    '<span class="chat-broadcast-chip">Viewed by ' +
                    (m.viewed_count || 0) +
                    " orang</span>" +
                    "</div>";
            }

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
    }

    document.addEventListener("DOMContentLoaded", function () {
        cacheElements();
        bindEvents();
        loadChannels(false);
    });
})();

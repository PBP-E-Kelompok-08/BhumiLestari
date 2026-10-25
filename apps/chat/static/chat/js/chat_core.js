window.ChatCore = (function () {
    "use strict";

    function getCsrfToken() {
        var meta = document.querySelector('meta[name="csrf-token"]');
        if (meta && meta.getAttribute("content")) {
            return meta.getAttribute("content");
        }
        var match = document.cookie.match(/csrftoken=([^;]+)/);
        return match ? decodeURIComponent(match[1]) : "";
    }

    async function apiFetch(url, options) {
        var opts = Object.assign({ method: "GET", headers: {} }, options || {});
        opts.headers["X-CSRFToken"] = getCsrfToken();
        opts.headers["Accept"] = "application/json";
        if (opts.body && typeof opts.body === "object" && !(opts.body instanceof FormData)) {
            opts.headers["Content-Type"] = "application/json";
            opts.body = JSON.stringify(opts.body);
        }

        var response = await fetch(url, opts);
        var data = {};
        try {
            data = await response.json();
        } catch (err) {
            data = { status: "error", message: "Respons server bukan JSON yang valid." };
        }
        if (!response.ok) {
            var errorMsg = data.message || ("Permintaan gagal (" + response.status + ")");
            var error = new Error(errorMsg);
            error.status = response.status;
            error.payload = data;
            throw error;
        }
        return data;
    }

    var toastTimer = null;
    function showToast(message) {
        var toastEl = document.getElementById("chatToast");
        if (!toastEl) return;
        toastEl.textContent = message;
        toastEl.hidden = false;
        if (toastTimer) clearTimeout(toastTimer);
        toastTimer = setTimeout(function () {
            toastEl.hidden = true;
        }, 3200);
    }

    function escapeHtml(text) {
        if (text === null || text === undefined) return "";
        return String(text)
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;")
            .replace(/'/g, "&#039;");
    }

    function formatTimeHM(isoStr) {
        if (!isoStr) return "";
        try {
            var d = new Date(isoStr);
            if (isNaN(d.getTime())) return "";
            var hh = String(d.getHours()).padStart(2, "0");
            var mm = String(d.getMinutes()).padStart(2, "0");
            return hh + "." + mm;
        } catch (e) {
            return "";
        }
    }

    function getAvatarSvgHtml() {
        return (
            '<div class="chat-avatar-circle" aria-hidden="true">' +
            '<svg viewBox="0 0 48 48">' +
            '<circle cx="24" cy="24" r="24" fill="#D8D4D5"/>' +
            '<circle cx="24" cy="18" r="7.5" fill="#706869"/>' +
            '<path d="M10 42c0-7.7 6.3-13 14-13s14 5.3 14 13" fill="#706869"/>' +
            "</svg>" +
            "</div>"
        );
    }

    function getArchiveIconSvgHtml() {
        return (
            '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' +
            '<rect x="3" y="4" width="18" height="4" rx="1"/>' +
            '<path d="M5 8v11a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8"/>' +
            '<path d="M12 11v6"/>' +
            '<path d="M9.5 14.5L12 17l2.5-2.5"/>' +
            "</svg>"
        );
    }

    function openModal(backdropId) {
        var el = document.getElementById(backdropId);
        if (!el) return;
        el.hidden = false;
        var focusTarget = el.querySelector("textarea, input:not([type='hidden']), select, button:not(.chat-modal-close)");
        if (focusTarget) {
            setTimeout(function () {
                focusTarget.focus();
            }, 30);
        }
    }

    function closeModal(backdropId) {
        var el = document.getElementById(backdropId);
        if (el) el.hidden = true;
    }

    function initCommonModals() {
        // Escape key closes any open modal or dropdown
        document.addEventListener("keydown", function (e) {
            if (e.key === "Escape") {
                var modals = document.querySelectorAll(".chat-modal-backdrop:not([hidden])");
                modals.forEach(function (m) {
                    m.hidden = true;
                });
                var dropdowns = document.querySelectorAll(".chat-header-dropdown:not([hidden])");
                dropdowns.forEach(function (d) {
                    d.hidden = true;
                });
            }
        });

        // Click on modal backdrop outside dialog closes modal
        document.querySelectorAll(".chat-modal-backdrop").forEach(function (backdrop) {
            backdrop.addEventListener("click", function (e) {
                if (e.target === backdrop) {
                    backdrop.hidden = true;
                }
            });
        });

        // Star Rating Selector in Screen 7 Popover
        var starBtns = document.querySelectorAll(".chat-star-btn");
        var ratingInput = document.getElementById("ratingValueInput");
        starBtns.forEach(function (btn) {
            btn.addEventListener("click", function () {
                var val = parseInt(btn.getAttribute("data-star"), 10) || 5;
                if (ratingInput) ratingInput.value = String(val);
                starBtns.forEach(function (b) {
                    var bVal = parseInt(b.getAttribute("data-star"), 10) || 0;
                    b.classList.toggle("active", bVal <= val);
                });
            });
        });

        var closeRatingBtn = document.getElementById("closeRatingModalBtn");
        if (closeRatingBtn) {
            closeRatingBtn.addEventListener("click", function () {
                closeModal("ratingModalBackdrop");
            });
        }

        var closeReportBtn = document.getElementById("closeReportModalBtn");
        if (closeReportBtn) {
            closeReportBtn.addEventListener("click", function () {
                closeModal("reportModalBackdrop");
            });
        }

        var closeProductBtn = document.getElementById("closeProductModalBtn");
        if (closeProductBtn) {
            closeProductBtn.addEventListener("click", function () {
                closeModal("productContextModalBackdrop");
            });
        }

        // Mobile back button to show sidebar list
        var mobileBackBtn = document.getElementById("mobileBackToListBtn");
        var shell = document.getElementById("chatShell");
        if (mobileBackBtn && shell) {
            mobileBackBtn.addEventListener("click", function () {
                shell.classList.remove("mobile-thread-active");
            });
        }
    }

    document.addEventListener("DOMContentLoaded", initCommonModals);

    return {
        getCsrfToken: getCsrfToken,
        apiFetch: apiFetch,
        showToast: showToast,
        escapeHtml: escapeHtml,
        formatTimeHM: formatTimeHM,
        getAvatarSvgHtml: getAvatarSvgHtml,
        getArchiveIconSvgHtml: getArchiveIconSvgHtml,
        openModal: openModal,
        closeModal: closeModal
    };
})();


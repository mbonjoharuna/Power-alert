/**
 * Douala Power Alert — client-side JS
 * Bilingual form validation (French default & English), mobile menu,
 * Leaflet map markers with radar pulses, password toggles,
 * PWA installation banner, offline fallback caching & notifications.
 */

function getLang() {
    return document.documentElement.lang || "fr";
}

var JS_TEXTS = {
    fr: {
        fillAllFields: "Veuillez remplir tous les champs obligatoires.",
        passwordLength: "Le mot de passe doit comporter au moins 6 caractères.",
        validEmail: "Veuillez saisir une adresse email valide.",
        emailPasswordRequired: "L'email et le mot de passe sont obligatoires.",
        reportRequired: "Le quartier, le lieu et l'heure de coupure sont obligatoires.",
        confirmStillOff: "Confirmez-vous que l'électricité est toujours COUPÉE dans cette zone ?",
        confirmRestored: "Confirmez-vous que l'électricité a été RÉTABLIE ?",
        statusOff: "🔴 COUPÉ",
        statusRestored: "🟢 RÉTABLI",
        statusPending: "🟡 EN ATTENTE",
        details: "Voir les détails →",
        offlinePill: "📶 Mode Hors-Ligne · Urgences",
        cachedNotice: "Données locales en cache"
    },
    en: {
        fillAllFields: "Please fill in all required fields.",
        passwordLength: "Password must be at least 6 characters.",
        validEmail: "Please enter a valid email address.",
        emailPasswordRequired: "Email and password are required.",
        reportRequired: "Neighborhood, location and start time are required.",
        confirmStillOff: "Confirm that electricity is still OFF in this area?",
        confirmRestored: "Confirm that electricity has been RESTORED?",
        statusOff: "🔴 OFF",
        statusRestored: "🟢 RESTORED",
        statusPending: "🟡 PENDING",
        details: "View details →",
        offlinePill: "📶 Offline Mode · Utilities",
        cachedNotice: "Locally cached data"
    }
};

function t_js(key) {
    var lang = getLang();
    var dict = JS_TEXTS[lang] || JS_TEXTS["fr"];
    return dict[key] || (JS_TEXTS["fr"][key] || key);
}

// ---------- Mobile menu, Password Toggles & PWA Init ----------
document.addEventListener("DOMContentLoaded", function () {
    var toggle = document.getElementById("menuToggle");
    var links = document.querySelector(".nav-links");
    if (toggle && links) {
        toggle.addEventListener("click", function () {
            links.classList.toggle("open");
        });
    }

    // Client-side form validation
    setupFormValidation();

    // Password visibility toggles
    setupPasswordToggles();

    // In-app & Web Push Notification Center
    setupNotifications();

    // PWA In-App Install Prompt Banner
    setupPwa();

    // Network connectivity detection
    setupOfflineDetection();
});

function setupPasswordToggles() {
    document.querySelectorAll(".password-toggle-btn").forEach(function (btn) {
        btn.addEventListener("click", function () {
            var targetId = btn.getAttribute("data-target") || "password";
            var input = document.getElementById(targetId);
            if (input) {
                if (input.type === "password") {
                    input.type = "text";
                    btn.textContent = "🙈";
                    btn.setAttribute("title", "Hide password");
                } else {
                    input.type = "password";
                    btn.textContent = "👁️";
                    btn.setAttribute("title", "Show password");
                }
            }
        });
    });
}

function setupFormValidation() {
    var registerForm = document.getElementById("registerForm");
    if (registerForm) {
        registerForm.addEventListener("submit", function (e) {
            var email = document.getElementById("email").value.trim();
            var phone = document.getElementById("phone").value.trim();
            var password = document.getElementById("password").value;
            var name = document.getElementById("full_name").value.trim();
            var neighborhood = document.getElementById("neighborhood").value.trim();

            if (!name || !email || !phone || !password || !neighborhood) {
                e.preventDefault();
                alert(t_js("fillAllFields"));
                return;
            }
            if (password.length < 6) {
                e.preventDefault();
                alert(t_js("passwordLength"));
                return;
            }
            if (!email.includes("@")) {
                e.preventDefault();
                alert(t_js("validEmail"));
                return;
            }
        });
    }

    var loginForm = document.getElementById("loginForm");
    if (loginForm) {
        loginForm.addEventListener("submit", function (e) {
            var email = document.getElementById("email").value.trim();
            var password = document.getElementById("password").value;
            if (!email || !password) {
                e.preventDefault();
                alert(t_js("emailPasswordRequired"));
            }
        });
    }

    var reportForm = document.getElementById("reportForm");
    if (reportForm) {
        reportForm.addEventListener("submit", function (e) {
            var neighborhood = document.getElementById("neighborhood").value.trim();
            var location = document.getElementById("location").value.trim();
            var startTime = document.getElementById("start_time").value;
            if (!neighborhood || !location || !startTime) {
                e.preventDefault();
                alert(t_js("reportRequired"));
            }
        });
    }
}

// ---------- Confirmation dialog ----------
function confirmAction(form) {
    var btn = document.activeElement;
    var value = btn ? btn.value : "";
    if (value === "STILL_OFF") {
        return confirm(t_js("confirmStillOff"));
    }
    if (value === "RESTORED") {
        return confirm(t_js("confirmRestored"));
    }
    return true;
}

// ---------- Interactive map (Leaflet with Radar Markers & Offline Cache Fallback) ----------
function initOutageMap(elementId) {
    var el = document.getElementById(elementId);
    if (!el || typeof L === "undefined") return;

    // Douala center
    var map = L.map(elementId, {
        zoomControl: true,
        scrollWheelZoom: false
    }).setView([4.0511, 9.7679], 12);

    L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
        attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
        maxZoom: 18,
    }).addTo(map);

    function renderMarkers(markers) {
        markers.forEach(function (m) {
            var color = "#ef4444"; // red = off
            var pulseColor = "rgba(239, 68, 68, 0.45)";
            var label = t_js("statusOff");
            var showPulse = true;

            if (m.status === "RESTORED") {
                color = "#10b981";
                pulseColor = "transparent";
                label = t_js("statusRestored");
                showPulse = false;
            } else if (m.status === "PENDING") {
                color = "#f59e0b";
                pulseColor = "rgba(245, 158, 11, 0.4)";
                label = t_js("statusPending");
            }

            var pulseHtml = showPulse ? '<div class="marker-pulse" style="background:' + pulseColor + '"></div>' : '';
            var iconHtml = '<div class="custom-marker-wrap">' +
                            pulseHtml +
                            '<div class="marker-core" style="background:' + color + '"></div>' +
                           '</div>';

            var icon = L.divIcon({
                className: "custom-leaflet-marker",
                html: iconHtml,
                iconSize: [20, 20],
                iconAnchor: [10, 10],
                popupAnchor: [0, -10]
            });

            var marker = L.marker([m.lat, m.lng], { icon: icon }).addTo(map);
            marker.bindPopup(
                '<div style="font-family: inherit;">' +
                    '<div style="font-size:1rem; font-weight:800; color:#f8fafc; margin-bottom:4px;">' +
                        m.neighborhood +
                    '</div>' +
                    '<div style="color:#94a3b8; font-size:0.85rem; margin-bottom:8px;">' +
                        m.location +
                    '</div>' +
                    '<div style="font-weight:700; font-size:0.85rem; margin-bottom:8px;">' +
                        label +
                    '</div>' +
                    '<a href="/outage/' + m.id + '" style="color:#38bdf8; font-weight:700; text-decoration:none; font-size:0.85rem;">' +
                        t_js("details") +
                    '</a>' +
                '</div>'
            );
        });
    }

    // Fetch markers from API, with localStorage cache fallback
    fetch("/api/outages/map")
        .then(function (res) {
            return res.json();
        })
        .then(function (markers) {
            // Save to localStorage for offline viewing
            try {
                localStorage.setItem("douala_cached_outages", JSON.stringify(markers));
                localStorage.setItem("douala_cached_timestamp", new Date().toISOString());
            } catch (err) {}

            renderMarkers(markers);
        })
        .catch(function () {
            // Fallback: load from cache if offline
            try {
                var cached = localStorage.getItem("douala_cached_outages");
                if (cached) {
                    var parsed = JSON.parse(cached);
                    if (parsed && parsed.length > 0) {
                        renderMarkers(parsed);
                    }
                }
            } catch (e) {}
        });
}

// ===========================================================================
// In-App & Web Push Notification Center
// ===========================================================================

function setupNotifications() {
    var bellContainer = document.getElementById("notifBellContainer");
    if (!bellContainer) return; // User not logged in

    var bellBtn = document.getElementById("notifBellBtn");
    var notifBadge = document.getElementById("notifBadge");
    var notifDropdown = document.getElementById("notifDropdown");
    var notifList = document.getElementById("notifList");
    var notifMarkAllReadBtn = document.getElementById("notifMarkAllReadBtn");
    var notifBrowserPrompt = document.getElementById("notifBrowserPrompt");
    var btnEnablePush = document.getElementById("btnEnablePush");

    // 1. Service Worker registration
    if ("serviceWorker" in navigator) {
        navigator.serviceWorker.register("/static/sw.js").catch(function () {});
    }

    // 2. Browser Push Permission Check
    if ("Notification" in window) {
        if (Notification.permission === "granted") {
            if (btnEnablePush) {
                btnEnablePush.textContent = getLang() === "fr" ? "Activées ✓" : "Active ✓";
                btnEnablePush.disabled = true;
                btnEnablePush.style.background = "#10b981";
            }
        } else if (Notification.permission === "denied") {
            if (notifBrowserPrompt) notifBrowserPrompt.style.display = "none";
        }

        if (btnEnablePush) {
            btnEnablePush.addEventListener("click", function () {
                Notification.requestPermission().then(function (perm) {
                    if (perm === "granted") {
                        btnEnablePush.textContent = getLang() === "fr" ? "Activées ✓" : "Active ✓";
                        btnEnablePush.disabled = true;
                        btnEnablePush.style.background = "#10b981";
                        triggerWebPush({
                            title: getLang() === "fr" ? "⚡ Notifications activées" : "⚡ Notifications Enabled",
                            message: getLang() === "fr" ? "Vous recevrez désormais des alertes dès qu'une coupure survient dans votre quartier !" : "You will now receive alerts whenever an outage occurs in your neighborhood!"
                        });
                    }
                });
            });
        }
    } else if (notifBrowserPrompt) {
        notifBrowserPrompt.style.display = "none";
    }

    // 3. Audio Chime via Web Audio API
    function playNotificationChime() {
        try {
            var AudioCtx = window.AudioContext || window.webkitAudioContext;
            if (!AudioCtx) return;
            var ctx = new AudioCtx();
            var osc = ctx.createOscillator();
            var gain = ctx.createGain();
            osc.type = "sine";
            osc.frequency.setValueAtTime(587.33, ctx.currentTime); // D5
            osc.frequency.setValueAtTime(880, ctx.currentTime + 0.12); // A5
            gain.gain.setValueAtTime(0.12, ctx.currentTime);
            gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + 0.35);
            osc.connect(gain);
            gain.connect(ctx.destination);
            osc.start();
            osc.stop(ctx.currentTime + 0.35);
        } catch (e) {}
    }

    // 4. Trigger Web Push / Desktop Notification
    function triggerWebPush(notif) {
        if (!("Notification" in window) || Notification.permission !== "granted") {
            return;
        }

        var title = notif.title || "Douala Power Alert";
        var options = {
            body: notif.message,
            icon: "/static/img/icon-192.png",
            badge: "/static/img/icon-bolt.svg",
            data: { url: notif.outage_id ? "/outage/" + notif.outage_id : "/outages" }
        };

        if (navigator.serviceWorker && navigator.serviceWorker.controller) {
            navigator.serviceWorker.ready.then(function (reg) {
                reg.showNotification(title, options);
            });
        } else {
            var n = new Notification(title, options);
            n.onclick = function () {
                window.focus();
                if (notif.outage_id) {
                    window.location.href = "/outage/" + notif.outage_id;
                }
            };
        }
    }

    // 5. Update Badge Count
    function updateBadge(count) {
        if (!notifBadge) return;
        if (count > 0) {
            notifBadge.textContent = count > 99 ? "99+" : count;
            notifBadge.style.display = "flex";
        } else {
            notifBadge.style.display = "none";
        }
    }

    // 6. Render Notifications List
    function renderList(notifications) {
        if (!notifList) return;
        if (!notifications || notifications.length === 0) {
            notifList.innerHTML = '<div class="notif-empty">' + (getLang() === 'fr' ? 'Aucune notification pour votre quartier.' : 'No notifications for your neighborhood.') + '</div>';
            return;
        }

        var html = "";
        notifications.forEach(function (n) {
            var icon = "⚡";
            if (n.type === "OUTAGE_VERIFIED") icon = "⚠️";
            else if (n.type === "OUTAGE_RESTORED") icon = "💡";
            else if (n.type === "OUTAGE_ESTIMATE") icon = "🕒";

            var unreadClass = n.is_read ? "" : " unread";
            var url = n.outage_id ? "/outage/" + n.outage_id : "/outages";

            html += '<a href="' + url + '" class="notif-item' + unreadClass + '">' +
                        '<div class="notif-item-icon">' + icon + '</div>' +
                        '<div class="notif-item-content">' +
                            '<div class="notif-item-title">' + n.title + '</div>' +
                            '<div class="notif-item-msg">' + n.message + '</div>' +
                            '<div class="notif-item-time">' + n.created_at + '</div>' +
                        '</div>' +
                    '</a>';
        });

        notifList.innerHTML = html;
    }

    // 7. Fetch Notifications from Server
    function loadNotifications(isInitial) {
        fetch("/api/notifications")
            .then(function (res) { return res.json(); })
            .then(function (data) {
                updateBadge(data.unread_count || 0);
                renderList(data.notifications || []);

                // Detect new notifications to fire browser alerts
                if (data.notifications && data.notifications.length > 0) {
                    var latest = data.notifications[0];
                    var lastSeen = parseInt(localStorage.getItem("douala_last_notif_id") || "0", 10);

                    if (!isInitial && latest.id > lastSeen && !latest.is_read) {
                        triggerWebPush(latest);
                        playNotificationChime();
                    }
                    localStorage.setItem("douala_last_notif_id", latest.id.toString());
                }
            })
            .catch(function () {});
    }

    // Initial load
    loadNotifications(true);

    // Poll every 15 seconds for real-time neighborhood updates
    setInterval(function () {
        loadNotifications(false);
    }, 15000);

    // 8. Toggle Dropdown on Bell Click
    if (bellBtn && notifDropdown) {
        bellBtn.addEventListener("click", function (e) {
            e.stopPropagation();
            var isHidden = notifDropdown.style.display === "none";
            notifDropdown.style.display = isHidden ? "block" : "none";
            if (isHidden) {
                loadNotifications(false);
            }
        });

        // Close dropdown when clicking outside
        document.addEventListener("click", function (e) {
            if (!bellContainer.contains(e.target)) {
                notifDropdown.style.display = "none";
            }
        });
    }

    // 9. Mark All as Read
    if (notifMarkAllReadBtn) {
        notifMarkAllReadBtn.addEventListener("click", function (e) {
            e.stopPropagation();
            var meta = document.querySelector('meta[name="csrf-token"]');
            var token = meta ? meta.getAttribute("content") : "";

            fetch("/api/notifications/mark-read", {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                    "X-CSRFToken": token
                },
                body: JSON.stringify({})
            })
            .then(function (res) { return res.json(); })
            .then(function () {
                updateBadge(0);
                loadNotifications(false);
            })
            .catch(function () {});
        });
    }
}

// ===========================================================================
// Progressive Web App (PWA) Install Prompt
// ===========================================================================

var deferredInstallPrompt = null;

window.addEventListener("beforeinstallprompt", function (e) {
    e.preventDefault();
    deferredInstallPrompt = e;

    // Check if dismissed within the past 24 hours
    var dismissedAt = localStorage.getItem("douala_pwa_dismissed");
    if (dismissedAt && (Date.now() - parseInt(dismissedAt, 10) < 86400000)) {
        return;
    }

    var banner = document.getElementById("pwaInstallBanner");
    if (banner) {
        banner.style.display = "block";
    }
});

function setupPwa() {
    var btnInstall = document.getElementById("btnPwaInstall");
    var btnDismiss = document.getElementById("btnPwaDismiss");
    var banner = document.getElementById("pwaInstallBanner");

    if (btnInstall) {
        btnInstall.addEventListener("click", function () {
            if (deferredInstallPrompt) {
                deferredInstallPrompt.prompt();
                deferredInstallPrompt.userChoice.then(function (choice) {
                    if (choice.outcome === "accepted") {
                        if (banner) banner.style.display = "none";
                    }
                    deferredInstallPrompt = null;
                });
            }
        });
    }

    if (btnDismiss) {
        btnDismiss.addEventListener("click", function () {
            if (banner) banner.style.display = "none";
            localStorage.setItem("douala_pwa_dismissed", Date.now().toString());
        });
    }

    window.addEventListener("appinstalled", function () {
        if (banner) banner.style.display = "none";
        deferredInstallPrompt = null;
    });
}

// ===========================================================================
// Offline Connectivity Detection
// ===========================================================================

function setupOfflineDetection() {
    function updateOnlineStatus() {
        var existingPill = document.getElementById("offlineStatusPill");
        if (!navigator.onLine) {
            if (!existingPill) {
                var pill = document.createElement("a");
                pill.id = "offlineStatusPill";
                pill.href = "/offline";
                pill.style.cssText = "position:fixed; bottom:20px; right:20px; background:rgba(239,68,68,0.92); backdrop-filter:blur(10px); color:white; padding:9px 18px; border-radius:9999px; font-weight:800; font-size:0.84rem; z-index:9998; box-shadow:0 8px 24px rgba(0,0,0,0.6); display:inline-flex; align-items:center; gap:8px; text-decoration:none; border:1px solid rgba(255,255,255,0.2);";
                pill.innerHTML = '<span>📶</span> ' + t_js("offlinePill");
                document.body.appendChild(pill);
            }
        } else {
            if (existingPill) {
                existingPill.remove();
            }
        }
    }

    window.addEventListener("online", updateOnlineStatus);
    window.addEventListener("offline", updateOnlineStatus);
    updateOnlineStatus();
}

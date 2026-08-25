/**
 * Douala Power Alert — client-side JS
 * Bilingual form validation (French default & English), mobile menu, Leaflet map markers with radar pulses, password toggles
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
        details: "Voir les détails →"
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
        details: "View details →"
    }
};

function t_js(key) {
    var lang = getLang();
    var dict = JS_TEXTS[lang] || JS_TEXTS["fr"];
    return dict[key] || (JS_TEXTS["fr"][key] || key);
}

// ---------- Mobile menu & Password Toggles ----------
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

// ---------- Interactive map (Leaflet with Radar Markers) ----------
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

    // Fetch markers from our API
    fetch("/api/outages/map")
        .then(function (res) {
            return res.json();
        })
        .then(function (markers) {
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
                        '<div style="font-size:1rem; font-weight:800; color:#0f172a; margin-bottom:4px;">' +
                            m.neighborhood +
                        '</div>' +
                        '<div style="color:#64748b; font-size:0.85rem; margin-bottom:8px;">' +
                            m.location +
                        '</div>' +
                        '<div style="font-weight:700; font-size:0.85rem; margin-bottom:8px;">' +
                            label +
                        '</div>' +
                        '<a href="/outage/' + m.id + '" style="color:#2563eb; font-weight:700; text-decoration:none; font-size:0.85rem;">' +
                            t_js("details") +
                        '</a>' +
                    '</div>'
                );
            });
        })
        .catch(function () {
            // Silent fail – map still shows base tiles
        });
}



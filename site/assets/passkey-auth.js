// PWA service worker registration for /cpo + /quality.
//
// Brief #403 added a passkey (WebAuthn) login gate here that blocked the
// page behind a full-viewport overlay until a dip_session cookie was
// confirmed. Brief #495 removed that gate: Cloudflare Access now fronts
// these pages as the sole auth wall, and the app-level passkey check was
// stacking a second wall that broke ("Failed to fetch") whenever CF Access
// intercepted the request first. The login/enroll functions below are kept
// as dead code (matching the dip-service passkey routes, also left in
// place unused) rather than deleted, so the ceremony can be resurrected
// without re-deriving it if that's ever needed.
(function () {
  "use strict";

  var BASE = "https://dip-service-production-0db3.up.railway.app";
  var AUTH = BASE + "/ops/api/auth";

  function registerServiceWorker() {
    if ("serviceWorker" in navigator) {
      navigator.serviceWorker.register("/sw.js").catch(function (err) {
        console.warn("sw registration failed", err);
      });
    }
  }

  function b64urlToBuffer(b64url) {
    var pad = "=".repeat((4 - (b64url.length % 4)) % 4);
    var b64 = (b64url + pad).replace(/-/g, "+").replace(/_/g, "/");
    var str = atob(b64);
    var buf = new Uint8Array(str.length);
    for (var i = 0; i < str.length; i++) buf[i] = str.charCodeAt(i);
    return buf.buffer;
  }

  function bufferToB64url(buf) {
    var bytes = new Uint8Array(buf);
    var str = "";
    for (var i = 0; i < bytes.length; i++) str += String.fromCharCode(bytes[i]);
    return btoa(str).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
  }

  async function checkSession() {
    try {
      var r = await fetch(AUTH + "/session", { credentials: "include" });
      return r.ok;
    } catch (e) {
      return false;
    }
  }

  async function login() {
    var optRes = await fetch(AUTH + "/login/options", {
      method: "POST",
      credentials: "include",
    });
    if (!optRes.ok) throw new Error("could not start login");
    var options = await optRes.json();
    var publicKey = Object.assign({}, options, {
      challenge: b64urlToBuffer(options.challenge),
      allowCredentials: (options.allowCredentials || []).map(function (c) {
        return Object.assign({}, c, { id: b64urlToBuffer(c.id) });
      }),
    });
    var assertion = await navigator.credentials.get({ publicKey: publicKey });
    var credential = {
      id: assertion.id,
      rawId: bufferToB64url(assertion.rawId),
      type: assertion.type,
      response: {
        clientDataJSON: bufferToB64url(assertion.response.clientDataJSON),
        authenticatorData: bufferToB64url(assertion.response.authenticatorData),
        signature: bufferToB64url(assertion.response.signature),
        userHandle: assertion.response.userHandle
          ? bufferToB64url(assertion.response.userHandle)
          : null,
      },
    };
    var verifyRes = await fetch(AUTH + "/login/verify", {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ credential: credential, challenge: options.challenge }),
    });
    return verifyRes.ok;
  }

  async function enroll(token) {
    var optRes = await fetch(
      AUTH + "/enroll/options?enrollment_token=" + encodeURIComponent(token),
      { method: "POST", credentials: "include" }
    );
    if (!optRes.ok) throw new Error("could not start enrollment — token invalid or expired");
    var options = await optRes.json();
    var publicKey = Object.assign({}, options, {
      challenge: b64urlToBuffer(options.challenge),
      user: Object.assign({}, options.user, { id: b64urlToBuffer(options.user.id) }),
      excludeCredentials: (options.excludeCredentials || []).map(function (c) {
        return Object.assign({}, c, { id: b64urlToBuffer(c.id) });
      }),
    });
    var created = await navigator.credentials.create({ publicKey: publicKey });
    var credential = {
      id: created.id,
      rawId: bufferToB64url(created.rawId),
      type: created.type,
      response: {
        clientDataJSON: bufferToB64url(created.response.clientDataJSON),
        attestationObject: bufferToB64url(created.response.attestationObject),
        transports: created.response.getTransports ? created.response.getTransports() : [],
      },
    };
    var verifyRes = await fetch(AUTH + "/enroll/verify", {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        credential: credential,
        challenge: options.challenge,
        enrollment_token: token,
        device_label: navigator.userAgent,
      }),
    });
    return verifyRes.ok;
  }

  // ── overlay UI (self-contained styling; no dependency on host page CSS) ──

  var overlay, statusEl, buttonEl;

  function injectStyles() {
    var style = document.createElement("style");
    style.textContent =
      "#dip-passkey-gate{position:fixed;inset:0;z-index:99999;display:flex;" +
      "align-items:center;justify-content:center;flex-direction:column;gap:18px;" +
      "background:radial-gradient(ellipse 80% 60% at 15% 0%, rgba(51,44,179,.55) 0%, #03051F 55%);" +
      "font-family:system-ui,-apple-system,sans-serif;color:#E8E6DC;text-align:center;padding:24px}" +
      "#dip-passkey-gate .dip-mark{width:52px;height:52px;border-radius:16px;" +
      "background:linear-gradient(135deg,#332CB3,#456FDD);box-shadow:0 0 0 6px rgba(69,111,221,.18)}" +
      "#dip-passkey-gate h1{font-size:16px;font-weight:700;letter-spacing:.02em}" +
      "#dip-passkey-gate p{font-size:13px;color:rgba(232,230,220,.6);max-width:320px;line-height:1.5}" +
      "#dip-passkey-gate button{font-family:inherit;font-size:13.5px;font-weight:700;" +
      "padding:12px 22px;border-radius:10px;border:none;cursor:pointer;color:#fff;" +
      "background:linear-gradient(135deg,#332CB3,#456FDD)}" +
      "#dip-passkey-gate button:disabled{opacity:.5;cursor:default}" +
      "#dip-passkey-gate .dip-err{color:#DB5461;font-size:12px}";
    document.head.appendChild(style);
  }

  function buildOverlay(title, subtitle, buttonLabel, onClick) {
    injectStyles();
    overlay = document.createElement("div");
    overlay.id = "dip-passkey-gate";
    overlay.innerHTML =
      '<div class="dip-mark"></div>' +
      "<h1>" + title + "</h1>" +
      "<p>" + subtitle + "</p>" +
      '<button type="button">' + buttonLabel + "</button>" +
      '<p class="dip-err" style="display:none"></p>';
    document.documentElement.appendChild(overlay);
    buttonEl = overlay.querySelector("button");
    statusEl = overlay.querySelector(".dip-err");
    buttonEl.addEventListener("click", onClick);
  }

  function showError(message) {
    statusEl.textContent = message;
    statusEl.style.display = "block";
    buttonEl.disabled = false;
  }

  function removeOverlay() {
    if (overlay && overlay.parentNode) overlay.parentNode.removeChild(overlay);
  }

  function showLoginGate() {
    buildOverlay(
      "DispensaryIntelligence Ops",
      "Sign in with your passkey (FaceID, Windows Hello, or Dashlane) to continue.",
      "Sign in with Passkey",
      async function () {
        buttonEl.disabled = true;
        try {
          var ok = await login();
          if (ok) removeOverlay();
          else showError("Passkey sign-in was not accepted. Try again.");
        } catch (e) {
          showError(e.message || "Passkey sign-in failed.");
        }
      }
    );
  }

  function showEnrollGate(token) {
    buildOverlay(
      "Register This Device",
      "One-time device registration. This creates a passkey (recommended: save it to Dashlane) that replaces Cloudflare Access login going forward.",
      "Register Passkey",
      async function () {
        buttonEl.disabled = true;
        try {
          var enrolled = await enroll(token);
          if (!enrolled) {
            showError("Registration failed. The enrollment link may have expired.");
            return;
          }
          var loggedIn = await login();
          if (loggedIn) removeOverlay();
          else {
            statusEl.style.display = "none";
            showLoginGate();
          }
        } catch (e) {
          showError(e.message || "Registration failed.");
        }
      }
    );
  }

  async function init() {
    // brief #495: no passkey gate — Cloudflare Access is the sole auth
    // wall now, so the page renders directly with no client-side check.
    registerServiceWorker();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();

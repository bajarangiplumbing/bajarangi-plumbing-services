/* =========================================================
   BAJARANGI PLUMBING SERVICES — site script
   Ported from the inline IIFE in PRD/index.html per
   implementation_plan.md §6 and §11 Phase 2.

   Every lookup is null-safe because this one file now serves
   15 pages, most of which have no pipe rig, no carousel and
   no keyword rails.

   Fixes applied to the ported code, each traceable to a named
   gap in implementation_plan.md §9 / PRD_website_pages.md §2.4:
   - resize is requestAnimationFrame-throttled (was unthrottled)
   - keyword + wordmark marquees pause when scrolled off-screen
   - mobile menu: Escape closes, focus is moved and returned,
     outside click closes
   - carousel announces the current card through a live region
   - form errors toggle a .bad class (the stylesheet's own
     mechanism) instead of writing inline styles
   - submit button gets idle -> sending -> sent states and is
     disabled after a successful handoff (duplicate-tap guard)
   NOTE: server-side validation, persistence, notification and
   idempotency remain out of scope here — see
   implementation_plan.md §5 "Internal operations", §6 and §7.
   ========================================================= */
(function () {
  "use strict";

  var body = document.body;
  var WA_NUMBER = body.getAttribute("data-wa") || "";
  var BIZ = body.getAttribute("data-biz") || "Bajarangi Plumbing Services";
  var reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  function $(sel, root) { return (root || document).querySelector(sel); }
  function $$(sel, root) { return Array.prototype.slice.call((root || document).querySelectorAll(sel)); }

  /* ------------------------------------------------------ nav */
  (function nav() {
    var burger = $("#burger");
    var links = $("#navLinks");
    if (!burger || !links) { return; }

    /* The accessible name has to follow the state, not just
       aria-expanded. This used to leave the label reading "Open menu"
       while the menu was open, so a screen-reader user was told to open
       something that was already open. Labels come from data-* attributes
       in partials/header.html so the strings stay with the markup and
       remain translatable. */
    function setLabel(isOpen) {
      var next = isOpen
        ? burger.getAttribute("data-label-close")
        : burger.getAttribute("data-label-open");
      if (next) { burger.setAttribute("aria-label", next); }
    }

    function close(returnFocus) {
      links.classList.remove("open");
      burger.setAttribute("aria-expanded", "false");
      setLabel(false);
      if (returnFocus) { burger.focus(); }
    }
    function open() {
      links.classList.add("open");
      burger.setAttribute("aria-expanded", "true");
      setLabel(true);
      var first = $("a", links);
      if (first) { first.focus(); }
    }

    burger.addEventListener("click", function () {
      if (links.classList.contains("open")) { close(false); } else { open(); }
    });

    links.addEventListener("click", function (e) {
      if (e.target.tagName === "A") { close(false); }
    });

    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape" && links.classList.contains("open")) { close(true); }
    });

    document.addEventListener("click", function (e) {
      if (!links.classList.contains("open")) { return; }
      if (links.contains(e.target) || burger.contains(e.target)) { return; }
      close(false);
    });
  }());

  /* -------------------------------------------------- reveal */
  (function reveal() {
    var rv = $$(".rv");
    if (!rv.length) { return; }
    if (reduce || !("IntersectionObserver" in window)) {
      rv.forEach(function (e) { e.classList.add("in"); });
      return;
    }
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (x) {
        if (x.isIntersecting) { x.target.classList.add("in"); io.unobserve(x.target); }
      });
    }, { threshold: 0.14, rootMargin: "0px 0px -8% 0px" });
    rv.forEach(function (e) { io.observe(e); });
  }());

  /* ------------------------------- marquee off-screen pausing
     Closes the "four marquees animate continuously regardless of
     scroll position or viewport visibility" miss in PRD §2.4. */
  (function marquees() {
    var tracks = $$(".rail, .wordmark-strip");
    if (!tracks.length || reduce || !("IntersectionObserver" in window)) { return; }
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (x) {
        var target = x.target.classList.contains("rail")
          ? x.target
          : $(".wordmark-track", x.target);
        if (!target) { return; }
        target.classList.toggle("paused", !x.isIntersecting);
      });
    }, { threshold: 0 });
    tracks.forEach(function (t) { io.observe(t); });
  }());

  /* --------------------------- 3D scroll-scrubbed pipe network */
  (function pipes() {
    var rigs = $$(".piperig");
    var drawables = $$(".pipe-draw");
    var city = $("#bgCity");
    var temple = $("#bgTemple");
    var sky = $("#bgSky");

    drawables.forEach(function (p) {
      var L = p.getTotalLength();
      p.style.strokeDasharray = L + " " + L;
      p.style.strokeDashoffset = reduce ? 0 : L;
      p.dataset.len = L;
    });

    if (reduce) { return; }
    if (!rigs.length && !city && !temple && !sky) { return; }

    function scrub() {
      rigs.forEach(function (rig) {
        var r = rig.getBoundingClientRect();
        var vh = window.innerHeight;
        var p = (vh - r.top) / (vh * 0.85 + r.height * 0.5);
        p = Math.max(0, Math.min(1, p));

        var svg = rig.querySelector("svg");
        if (svg) {
          var rotY = (1 - p) * 16;
          var rotX = (1 - p) * -8;
          var tz = (1 - p) * -90;
          svg.style.transform = "rotateY(" + rotY + "deg) rotateX(" + rotX + "deg) translateZ(" + tz + "px)";
        }
        $$(".pipe-draw", rig).forEach(function (pipe, i) {
          var L = +pipe.dataset.len;
          var lag = (i % 3) * 0.08;
          var q = Math.max(0, Math.min(1, (p - lag) / (1 - lag || 1)));
          pipe.style.strokeDashoffset = L * (1 - q);
        });
        $$(".joint", rig).forEach(function (j) { j.classList.toggle("on", p > 0.55); });
        $$(".cap", rig).forEach(function (c) { c.classList.toggle("on", p > 0.8); });
      });

      var y = window.scrollY;
      if (city) { city.style.transform = "translateY(" + (y * 0.06) + "px)"; }
      if (temple) { temple.style.transform = "translateY(" + (y * 0.03) + "px)"; }
      if (sky) { sky.style.transform = "translateY(" + (-y * 0.02) + "px)"; }
    }

    var tick = false;
    function request() {
      if (tick) { return; }
      tick = true;
      window.requestAnimationFrame(function () { scrub(); tick = false; });
    }
    window.addEventListener("scroll", request, { passive: true });
    window.addEventListener("resize", request);
    scrub();
  }());

  /* ------------------------------------------- arc carousel */
  (function carousel() {
    var cards = $$(".car-card");
    var prev = $("#carPrev");
    var next = $("#carNext");
    var status = $("#carStatus");
    if (!cards.length || !prev || !next) { return; }
    var idx = 0;

    function layout() {
      cards.forEach(function (c, i) {
        var d = i - idx;
        var ad = Math.abs(d);
        c.style.transform = "translateX(" + (d * 185) + "px) translateY(" + (ad * ad * 16) +
          "px) rotate(" + (d * 7) + "deg) scale(" + (1 - ad * 0.11) + ")";
        c.style.opacity = ad > 2 ? 0 : 1 - ad * 0.22;
        c.style.zIndex = String(20 - ad);
        c.setAttribute("aria-hidden", d === 0 ? "false" : "true");
      });
      if (status) { status.textContent = (idx + 1) + " of " + cards.length; }
    }
    prev.addEventListener("click", function () { idx = (idx - 1 + cards.length) % cards.length; layout(); });
    next.addEventListener("click", function () { idx = (idx + 1) % cards.length; layout(); });
    layout();
  }());

  /* ------------------------------------------ form utilities */
  function fieldOf(el) { return el.closest(".field") || el.parentNode; }

  function mark(el, bad) {
    var wrap = fieldOf(el);
    if (bad) { el.setAttribute("aria-invalid", "true"); } else { el.removeAttribute("aria-invalid"); }
    if (wrap && wrap.classList) { wrap.classList.toggle("bad", !!bad); }
    return !!bad;
  }

  /* Fills the form's role="alert" region with a count of what still needs
     attention (WCAG 3.3.1 / 3.3.3).

     Before this, validation marked each field and moved focus to the first
     invalid one. That is conformant as far as it goes, but it reveals the
     problems one at a time: a screen-reader user heard about field one,
     fixed it, resubmitted, and only then learned about field two. The
     summary states the scale up front.

     Cleared on a valid submit so a stale count never lingers. Written with
     textContent, never innerHTML - this string is assembled locally, but
     the habit is what stops the next edit introducing an injection. */
  function announceErrors(form, count) {
    var summary = $("[data-error-summary]", form);
    if (!summary) { return; }
    if (!count) {
      summary.textContent = "";
      return;
    }
    summary.textContent = count === 1
      ? "1 field needs attention. The reason is shown under that field."
      : count + " fields need attention. The reasons are shown under each field.";
  }

  function countInvalid(form) {
    return form.querySelectorAll('[aria-invalid="true"]').length;
  }

  /* The consent wording a customer actually saw. Recorded server-side so
     informed consent stays provable after the text is next reworded. */
  function consentVersion(form) {
    var el = form.querySelector('[name=consent_notice_version]');
    return el ? el.value : "";
  }

  function normalisePhone(v) {
    var d = String(v || "").replace(/\D/g, "");
    if (d.length === 12 && d.indexOf("91") === 0) { d = d.slice(2); }
    if (d.length === 11 && d[0] === "0") { d = d.slice(1); }
    return /^[6-9]\d{9}$/.test(d) ? d : "";
  }

  function waUrl(lines) {
    return "https://wa.me/" + WA_NUMBER + "?text=" + encodeURIComponent(lines.join("\n"));
  }

  /* Security review M3 - this no longer keeps a local copy.

     It used to append every submission (name, phone, address and the full
     description of the problem) to localStorage under "bajarangi_leads" /
     "bajarangi_bookings", with no expiry, no size cap, and no mention of
     it in /privacy/. That is a customer's personal data left on the device
     indefinitely, readable by any script on this origin and by the next
     person to use that browser - which on a shared family phone or a
     cyber-cafe machine is a real person, not a hypothetical one. It also
     had no reader: nothing in the site ever displayed it or sent it
     anywhere, so it carried risk and delivered nothing. The record that
     matters is the Lead row on the server.

     Nothing is written now, and this clears what earlier visits left
     behind so the fix reaches devices already carrying the data rather
     than only new visitors. */
  function purgeLegacyLocalCopies() {
    try {
      window.localStorage.removeItem("bajarangi_leads");
      window.localStorage.removeItem("bajarangi_bookings");
    } catch (err) {
      /* Private mode, or storage blocked: nothing was ever stored. */
    }
  }
  purgeLegacyLocalCopies();

  function handoff(form, url, okBox, linkEl, btn) {
    if (linkEl) { linkEl.href = url; }
    if (okBox) { okBox.classList.add("show"); }
    if (btn) {
      btn.disabled = true;
      btn.textContent = btn.getAttribute("data-label-sent") || "Request sent to WhatsApp";
    }
    window.open(url, "_blank", "noopener");
  }

  /* Build a user-facing error message that gives the customer a clear
     next step instead of a dead end.  The 429 case gets its own wording
     because "too many requests" is fixable by waiting, whereas a 500 is
     not the customer's fault.  Every other failure points the customer
     at the WhatsApp / phone fallback so the conversion path stays open. */
  function submissionErrorMessage(status) {
    if (status === 429) {
      return "You\u2019re submitting too quickly \u2014 please wait a moment and try again.";
    }
    var waLink = "https://wa.me/" + WA_NUMBER;
    return "Your request couldn\u2019t be saved right now. " +
      "Please try again in a minute, or contact us directly on " +
      "WhatsApp (" + waLink + ") so we can still help you.";
  }

  function showFormError(form, message, btn) {
    var errBox = $(".form-err-api", form);
    if (errBox) {
      errBox.textContent = message;
      errBox.classList.add("show");
    }
    if (btn) {
      btn.disabled = false;
      btn.textContent = btn.getAttribute("data-label-idle") || "Send request on WhatsApp";
    }
  }

  function resetFormError(form) {
    var errBox = $(".form-err-api", form);
    if (errBox) {
      errBox.textContent = "";
      errBox.classList.remove("show");
    }
  }

  /* ------------------------------- WhatsApp service-request form */
  $$("[data-lead-form]").forEach(function (form) {
    var okBox = $(".form-ok", form);
    var linkEl = $("[data-wa-link]", form);
    var btn = $("button[type=submit]", form);

    form.addEventListener("submit", function (e) {
      e.preventDefault();

      var elName = $("[data-f=name]", form);
      var elPhone = $("[data-f=phone]", form);
      var elArea = $("[data-f=area]", form);
      var elService = $("[data-f=service]", form);
      var elIssue = $("[data-f=issue]", form);
      var elConsent = $("[data-f=consent]", form);

      var name = elName.value.trim();
      var phone = normalisePhone(elPhone.value);
      var area = elArea.value.trim();
      var service = elService ? elService.value.trim() : "";
      var issue = elIssue.value.trim();

      var bad = false;
      bad = mark(elName, !name) || bad;
      bad = mark(elPhone, !phone) || bad;
      bad = mark(elArea, !area) || bad;
      bad = mark(elIssue, !issue) || bad;
      bad = mark(elConsent, !elConsent.checked) || bad;

      if (bad) {
        announceErrors(form, countInvalid(form));
        var firstBad = form.querySelector('[aria-invalid="true"]');
        if (firstBad) { firstBad.focus(); }
        return;
      }
      announceErrors(form, 0);

      if (btn) { btn.textContent = btn.getAttribute("data-label-sending") || "Opening WhatsApp…"; }
      resetFormError(form);

      var csrfToken = form.querySelector('[name=csrfmiddlewaretoken]') ? form.querySelector('[name=csrfmiddlewaretoken]').value : "";
      fetch("/api/lead/", {
        method: "POST",
        headers: {
          "Content-Type": "application/x-www-form-urlencoded",
          "X-CSRFToken": csrfToken
        },
        body: new URLSearchParams({
          name: name, phone: phone, area: area,
          service: service, issue: issue, consent: elConsent.checked ? "1" : "0",
          consent_notice_version: consentVersion(form),
          website: ""
        })
      }).then(function (response) {
        if (!response.ok) {
          showFormError(form, submissionErrorMessage(response.status), btn);
          return;
        }
        handoff(form, waUrl([
          "New plumbing request — " + BIZ,
          "",
          "Name: " + name,
          "Phone: +91 " + phone,
          "Area: " + area,
          "Service: " + (service || "Not specified"),
          "Issue: " + issue
        ]), okBox, linkEl, btn);
      }).catch(function () {
        showFormError(form, submissionErrorMessage(0), btn);
      });
    });
  });

  /* ---------------------------------------- booking request form */
  $$("[data-booking-form]").forEach(function (form) {
    var okBox = $(".form-ok", form);
    var linkEl = $("[data-wa-link]", form);
    var btn = $("button[type=submit]", form);

    form.addEventListener("submit", function (e) {
      e.preventDefault();

      var elName = $("[data-f=name]", form);
      var elPhone = $("[data-f=phone]", form);
      var elEmail = $("[data-f=email]", form);
      var elArea = $("[data-f=area]", form);
      var elService = $("[data-f=service]", form);
      var elWhen = $("[data-f=when]", form);
      var elSlot = $("[data-f=slot]", form);
      var elUrgency = $("[data-f=urgency]", form);
      var elMessage = $("[data-f=message]", form);
      var elConsent = $("[data-f=consent]", form);

      var name = elName.value.trim();
      var phone = normalisePhone(elPhone.value);
      var email = elEmail ? elEmail.value.trim() : "";
      var area = elArea.value.trim();
      var service = elService ? elService.value.trim() : "";
      var when = elWhen ? elWhen.value.trim() : "";
      var slot = elSlot ? elSlot.value.trim() : "";
      var urgency = elUrgency ? elUrgency.value.trim() : "";
      var message = elMessage ? elMessage.value.trim() : "";

      var bad = false;
      bad = mark(elName, !name) || bad;
      bad = mark(elPhone, !phone) || bad;
      bad = mark(elArea, !area) || bad;
      bad = mark(elService, !service) || bad;
      bad = mark(elWhen, !when) || bad;
      /* email is optional; only validated when something was typed */
      if (elEmail) { bad = mark(elEmail, !!email && !/^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/.test(email)) || bad; }
      bad = mark(elConsent, !elConsent.checked) || bad;

      if (bad) {
        announceErrors(form, countInvalid(form));
        var firstBad = form.querySelector('[aria-invalid="true"]');
        if (firstBad) { firstBad.focus(); }
        return;
      }
      announceErrors(form, 0);

      if (btn) { btn.textContent = btn.getAttribute("data-label-sending") || "Opening WhatsApp…"; }
      resetFormError(form);

      var lines = [
        "New booking request — " + BIZ,
        "",
        "Name: " + name,
        "Phone: +91 " + phone
      ];
      if (email) { lines.push("Email: " + email); }
      lines.push("Address / locality: " + area);
      lines.push("Service: " + service);
      lines.push("Preferred date: " + when + (slot ? " — " + slot : ""));
      if (urgency) { lines.push("Urgency: " + urgency); }
      if (message) { lines.push("Message: " + message); }

      var csrfToken = form.querySelector('[name=csrfmiddlewaretoken]') ? form.querySelector('[name=csrfmiddlewaretoken]').value : "";
      fetch("/api/booking/", {
        method: "POST",
        headers: {
          "Content-Type": "application/x-www-form-urlencoded",
          "X-CSRFToken": csrfToken
        },
        body: new URLSearchParams({
          name: name, phone: phone, email: email, area: area,
          service: service, preferred_date: when, preferred_time: slot,
          urgency: urgency, message: message, consent: elConsent.checked ? "1" : "0",
          consent_notice_version: consentVersion(form),
          website: ""
        })
      }).then(function (response) {
        if (!response.ok) {
          showFormError(form, submissionErrorMessage(response.status), btn);
          return;
        }
        handoff(form, waUrl(lines), okBox, linkEl, btn);
      }).catch(function () {
        showFormError(form, submissionErrorMessage(0), btn);
      });
    });
  });
}());

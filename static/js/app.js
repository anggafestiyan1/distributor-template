// ── Auto-dismiss alerts ───────────────────────────────────────────────────
document.addEventListener("DOMContentLoaded", function () {
  document.querySelectorAll(".alert.alert-dismissible").forEach(function (alert) {
    setTimeout(function () {
      const bsAlert = bootstrap.Alert.getOrCreateInstance(alert);
      if (bsAlert) bsAlert.close();
    }, 5000);
  });
});

// ── Bootstrap form field styling for Django forms ─────────────────────────
document.addEventListener("DOMContentLoaded", function () {
  document.querySelectorAll("input, select, textarea").forEach(function (el) {
    if (
      !el.classList.contains("form-control") &&
      !el.classList.contains("form-select") &&
      !el.classList.contains("form-check-input") &&
      el.type !== "submit" &&
      el.type !== "button" &&
      el.type !== "hidden" &&
      el.type !== "checkbox" &&
      el.type !== "radio"
    ) {
      el.classList.add(el.tagName === "SELECT" ? "form-select" : "form-control");
    }
  });
});

// ── Django formset: dynamic add row ──────────────────────────────────────
// Usage:
//   <button type="button" onclick="addFormsetRow('aliases', 'aliases')">Add</button>
//   Empty template row must have id="aliases-empty-row" and use __prefix__ placeholders.
function addFormsetRow(prefix, containerId) {
  const totalFormsInput = document.getElementById("id_" + prefix + "-TOTAL_FORMS");
  if (!totalFormsInput) return;

  const emptyRow = document.getElementById(prefix + "-empty-row");
  if (!emptyRow) return;

  // Use TOTAL_FORMS as the next index (it always equals the count of existing forms)
  const nextIndex = parseInt(totalFormsInput.value, 10);

  // Clone the empty template row
  const newRow = emptyRow.cloneNode(true);
  newRow.removeAttribute("id");
  newRow.style.display = "";
  newRow.classList.remove("d-none");

  // Replace __prefix__ placeholder with the actual index
  newRow.innerHTML = newRow.innerHTML
    .split(prefix + "-__prefix__-").join(prefix + "-" + nextIndex + "-")
    .split("id_" + prefix + "-__prefix__-").join("id_" + prefix + "-" + nextIndex + "-");

  // Clear any leftover values
  newRow.querySelectorAll("input[type=text], input[type=number], textarea").forEach(function (el) {
    el.value = "";
  });

  // Append to the formset container
  const container = document.getElementById(containerId + "-formset");
  if (container) {
    container.appendChild(newRow);
  }

  // Increment TOTAL_FORMS so the next click gets the right index
  totalFormsInput.value = nextIndex + 1;

  // Apply Bootstrap classes to the new inputs
  newRow.querySelectorAll("input:not([type=hidden]):not([type=checkbox]), select, textarea").forEach(function (el) {
    if (!el.classList.contains("form-control") && !el.classList.contains("form-select")) {
      el.classList.add(el.tagName === "SELECT" ? "form-select" : "form-control");
    }
  });

  // Focus the first text input in the new row
  const firstInput = newRow.querySelector("input[type=text], input[type=number], textarea");
  if (firstInput) firstInput.focus();
}

// ── Alias normalization preview ───────────────────────────────────────────
// Called onkeyup on alias input fields to show a preview of normalized value.
function previewAlias(inputEl, previewEl) {
  const raw = inputEl.value;
  // Client-side approximation of server-side normalize_header()
  let s = raw.trim().toLowerCase();
  s = s.replace(/[-\s]+/g, "_");
  s = s.replace(/[^a-z0-9_]/g, "");
  s = s.replace(/_+/g, "_");
  s = s.replace(/^_+|_+$/g, "");
  previewEl.textContent = s ? "→ " + s : "";
}

// ── Tab state persistence via URL hash ───────────────────────────────────
document.addEventListener("DOMContentLoaded", function () {
  // Activate tab from URL hash
  const hash = window.location.hash;
  if (hash) {
    const tabEl = document.querySelector('[data-bs-toggle="tab"][data-bs-target="' + hash + '"]');
    if (tabEl) {
      bootstrap.Tab.getOrCreateInstance(tabEl).show();
    }
  }

  // Update hash on tab change
  document.querySelectorAll('[data-bs-toggle="tab"]').forEach(function (tabEl) {
    tabEl.addEventListener("shown.bs.tab", function (e) {
      const target = e.target.getAttribute("data-bs-target");
      if (target) {
        history.replaceState(null, "", target);
      }
    });
  });
});

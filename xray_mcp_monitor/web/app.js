const state = {
  watches: [],
  refreshTimer: null,
};

const summaryCards = document.getElementById("summary-cards");
const watchList = document.getElementById("watch-list");
const createForm = document.getElementById("create-form");
const quickCheckForm = document.getElementById("quick-check-form");
const quickCheckOutput = document.getElementById("quick-check-output");
const refreshButton = document.getElementById("refresh-button");
const watchTemplate = document.getElementById("watch-card-template");

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: {
      "Content-Type": "application/json",
      ...(options.headers || {}),
    },
    ...options,
  });
  const data = await response.json();
  if (!response.ok) {
    throw new Error(data.error || `Request failed with status ${response.status}`);
  }
  return data;
}

function renderSummary(watches) {
  const counts = watches.reduce(
    (acc, watch) => {
      acc.total += 1;
      if (watch.enabled) acc.enabled += 1;
      const status = watch.last_result?.status || "idle";
      if (status === "healthy" || status === "healthy_with_warnings") acc.healthy += 1;
      if (status === "down" || status === "error") acc.alerts += 1;
      return acc;
    },
    { total: 0, enabled: 0, healthy: 0, alerts: 0 },
  );

  const cards = [
    { label: "Monitors", value: counts.total, caption: "Saved watches" },
    { label: "Enabled", value: counts.enabled, caption: "Running on schedule" },
    { label: "Healthy", value: counts.healthy, caption: "Latest status green" },
    { label: "Alerts", value: counts.alerts, caption: "Need attention" },
  ];

  summaryCards.innerHTML = cards
    .map(
      (card) => `
        <article class="summary-card">
          <span>${escapeHtml(card.label)}</span>
          <strong>${escapeHtml(card.value)}</strong>
          <span>${escapeHtml(card.caption)}</span>
        </article>
      `,
    )
    .join("");
}

function renderWatchList(watches) {
  if (!watches.length) {
    watchList.className = "watch-list empty-state";
    watchList.innerHTML = "<p>No monitors yet. Create one above to start tracking reachability.</p>";
    return;
  }

  watchList.className = "watch-list";
  watchList.innerHTML = "";

  for (const watch of watches) {
    const fragment = watchTemplate.content.cloneNode(true);
    const card = fragment.querySelector(".watch-card");
    const result = watch.last_result || null;
    const status = result?.status || "idle";

    fragment.querySelector(".watch-status-line").textContent = watch.enabled ? "Scheduled monitor" : "Paused monitor";
    fragment.querySelector(".watch-title").textContent = watch.node_name_keyword || watch.subscription_url;
    const pill = fragment.querySelector(".watch-pill");
    pill.textContent = status.replaceAll("_", " ");
    pill.classList.add(`status-${status}`);

    const meta = fragment.querySelector(".watch-meta");
    meta.innerHTML = [
      ["URL", watch.subscription_url],
      ["Interval", `${watch.interval_seconds}s`],
      ["Timeout", `${watch.timeout_seconds}s`],
      ["Next Run", watch.next_run_at || "Paused"],
      ["Updated", watch.updated_at],
      ["Watch ID", watch.watch_id],
    ]
      .map(
        ([label, value]) => `
          <div>
            <dt>${escapeHtml(label)}</dt>
            <dd>${escapeHtml(value)}</dd>
          </div>
        `,
      )
      .join("");

    const actions = fragment.querySelector(".watch-actions");
    actions.append(
      actionButton("Run now", "button-secondary", async () => {
        await api(`/api/watches/${encodeURIComponent(watch.watch_id)}/run`, { method: "POST", body: "{}" });
        flash("Manual check completed");
        await refresh();
      }),
    );
    actions.append(
      actionButton(watch.enabled ? "Pause" : "Enable", "button-ghost", async () => {
        const action = watch.enabled ? "disable" : "enable";
        await api(`/api/watches/${encodeURIComponent(watch.watch_id)}/${action}`, { method: "POST", body: "{}" });
        flash(watch.enabled ? "Monitor paused" : "Monitor enabled");
        await refresh();
      }),
    );
    actions.append(
      actionButton("Delete", "button-danger", async () => {
        if (!window.confirm("Remove this monitor?")) return;
        await api(`/api/watches/${encodeURIComponent(watch.watch_id)}`, { method: "DELETE" });
        flash("Monitor removed");
        await refresh();
      }),
    );

    const detail = fragment.querySelector(".watch-detail");
    detail.innerHTML = renderDetail(result, watch.last_error);

    watchList.append(card);
  }
}

function renderDetail(result, lastError) {
  if (!result) {
    return "<p class=\"empty-state\">No run yet. The first scheduled check will populate node details.</p>";
  }

  const summary = `
    <div class="quick-result-meta">
      <div><span>Matched</span><strong>${escapeHtml(result.matched_nodes)}</strong></div>
      <div><span>Reachable</span><strong>${escapeHtml(result.reachable_nodes)}</strong></div>
      <div><span>Unreachable</span><strong>${escapeHtml(result.unreachable_nodes)}</strong></div>
      <div><span>Unsupported</span><strong>${escapeHtml(result.unsupported_nodes)}</strong></div>
    </div>
  `;

  const nodes = result.nodes?.length
    ? `
      <div class="node-list">
        ${result.nodes
          .map(
            (node) => `
              <article class="node-item">
                <strong>${escapeHtml(node.name || `${node.host}:${node.port}`)}</strong>
                <span>${escapeHtml(node.scheme)} • ${escapeHtml(node.host)}:${escapeHtml(node.port)} • ${escapeHtml(node.status)}</span>
                <span>${escapeHtml(node.latency_ms ?? "n/a")} ms${node.error ? ` • ${escapeHtml(node.error)}` : ""}</span>
              </article>
            `,
          )
          .join("")}
      </div>
    `
    : "<p class=\"empty-state\">No node results yet.</p>";

  const errors = [...(result.errors || []), ...(lastError ? [lastError] : [])];
  const errorBlock = errors.length
    ? `<div class="node-item"><strong>Errors</strong><span>${errors.map(escapeHtml).join("<br />")}</span></div>`
    : "";

  return `<h4>Latest Run · ${escapeHtml(result.checked_at)}</h4>${summary}${nodes}${errorBlock}`;
}

function renderQuickCheck(payload) {
  const result = payload.result;
  quickCheckOutput.className = "quick-output";
  quickCheckOutput.innerHTML = `
    <h3>Quick Check · ${escapeHtml(result.status)}</h3>
    <div class="quick-result-meta">
      <div><span>Matched</span><strong>${escapeHtml(result.matched_nodes)}</strong></div>
      <div><span>Reachable</span><strong>${escapeHtml(result.reachable_nodes)}</strong></div>
      <div><span>Unreachable</span><strong>${escapeHtml(result.unreachable_nodes)}</strong></div>
      <div><span>Unsupported</span><strong>${escapeHtml(result.unsupported_nodes)}</strong></div>
    </div>
    ${renderDetail(result, null)}
  `;
}

function actionButton(label, className, onClick) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = `button button-inline ${className}`;
  button.textContent = label;
  button.addEventListener("click", async () => {
    button.disabled = true;
    try {
      await onClick();
    } catch (error) {
      flash(error.message, true);
    } finally {
      button.disabled = false;
    }
  });
  return button;
}

function formPayload(form) {
  const data = new FormData(form);
  return Object.fromEntries(
    [...data.entries()].map(([key, value]) => [key, typeof value === "string" ? value.trim() : value]),
  );
}

function flash(message, isError = false) {
  const notice = document.createElement("div");
  notice.className = `flash${isError ? " flash-error" : ""}`;
  notice.textContent = message;
  document.body.append(notice);
  window.setTimeout(() => notice.remove(), 3000);
}

async function refresh() {
  const payload = await api("/api/watches");
  state.watches = payload.watches || [];
  renderSummary(state.watches);
  renderWatchList(state.watches);
}

createForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const payload = formPayload(createForm);
  try {
    await api("/api/watches", {
      method: "POST",
      body: JSON.stringify({
        subscription_url: payload.subscription_url,
        interval_seconds: Number(payload.interval_seconds),
        timeout_seconds: Number(payload.timeout_seconds),
        node_name_keyword: payload.node_name_keyword || null,
      }),
    });
    createForm.reset();
    createForm.interval_seconds.value = "300";
    createForm.timeout_seconds.value = "5";
    flash("Monitor created");
    await refresh();
  } catch (error) {
    flash(error.message, true);
  }
});

quickCheckForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const payload = formPayload(quickCheckForm);
  try {
    const result = await api("/api/check-once", {
      method: "POST",
      body: JSON.stringify({
        subscription_url: payload.subscription_url,
        timeout_seconds: Number(payload.timeout_seconds),
        node_name_keyword: payload.node_name_keyword || null,
      }),
    });
    renderQuickCheck(result);
    flash("Quick check complete");
  } catch (error) {
    flash(error.message, true);
  }
});

refreshButton.addEventListener("click", async () => {
  try {
    await refresh();
    flash("Dashboard refreshed");
  } catch (error) {
    flash(error.message, true);
  }
});

async function bootstrap() {
  try {
    await refresh();
    state.refreshTimer = window.setInterval(refresh, 15000);
  } catch (error) {
    flash(error.message, true);
  }
}

bootstrap();

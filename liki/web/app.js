"use strict";

const endpoints = {
  incidents: "/incidents",
  status: "/status",
  requirements: "/requirements",
  queues: "/scheduler/queues",
  runs: "/scheduler/why-running",
  campaigns: "/campaigns",
  paper: "/paper/status",
  orders: "/paper/orders",
  governance: "/governance/proposals",
  reservations: "/risk/reservations",
};

let accessToken = null;
let dashboard = {};
let sessionVersion = 0;
let pendingStop = null;

const $ = (selector) => document.querySelector(selector);
const authPanel = $("#auth-panel");
const authForm = $("#auth-form");
const accessTokenInput = $("#access-token");
const authFeedback = $("#auth-feedback");
const consoleElement = $("#console");
const refreshFeedback = $("#refresh-feedback");
const emergencyStopDialog = $("#emergency-stop-dialog");

function text(value, fallback = "—") {
  if (value === null || value === undefined || value === "") return fallback;
  return String(value);
}

function dateTime(value) {
  if (!value) return "—";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.valueOf())) return text(value);
  return new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" }).format(parsed);
}

function number(value) {
  if (value === null || value === undefined || value === "") return "—";
  const parsed = Number(value);
  return Number.isFinite(parsed) ? new Intl.NumberFormat().format(parsed) : text(value);
}

function element(name, attributes = {}, content) {
  const node = document.createElement(name);
  for (const [key, value] of Object.entries(attributes)) {
    if (key === "className") node.className = value;
    else if (key.startsWith("data-")) node.setAttribute(key, value);
    else node[key] = value;
  }
  if (content !== undefined) node.textContent = text(content, "");
  return node;
}

function clear(node) {
  node.replaceChildren();
  return node;
}

function safeError(error) {
  if (error && error.kind === "http") {
    if (error.status === 401) return "Authentication was not accepted. Enter an approved operator token.";
    if (error.status === 403) return "Your role is not authorized for this operation.";
    return `The control plane returned ${error.code || `HTTP ${error.status}`}.`;
  }
  return "The control plane could not be reached. Check the network connection and retry.";
}

async function request(path, options = {}) {
  if (!accessToken) throw { kind: "http", status: 401, code: "UNAUTHENTICATED" };
  let response;
  try {
    response = await fetch(path, {
      ...options,
      headers: { Authorization: `Bearer ${accessToken}`, ...(options.headers || {}) },
    });
  } catch {
    throw { kind: "network" };
  }

  let payload = null;
  try { payload = await response.json(); } catch { payload = null; }
  if (!response.ok) throw { kind: "http", status: response.status, code: payload && payload.error };
  return payload;
}

function renderMessage(target, message, isError = false) {
  clear(target).append(element("p", { className: `empty-state${isError ? " error-state" : ""}` }, message));
}

function renderTable(target, columns, rows, emptyMessage, error) {
  clear(target);
  if (error) return renderMessage(target, safeError(error), true);
  if (!Array.isArray(rows) || rows.length === 0) return renderMessage(target, emptyMessage);

  const table = element("table");
  const headRow = element("tr");
  for (const column of columns) headRow.append(element("th", { scope: "col" }, column.label));
  const thead = element("thead");
  thead.append(headRow);
  table.append(thead);
  const body = element("tbody");
  for (const row of rows) {
    const tr = element("tr");
    for (const column of columns) {
      const raw = typeof column.value === "function" ? column.value(row) : row[column.value];
      const cell = element("td");
      if (column.badge) {
        const badge = element("span", { className: "state-badge", "data-state": text(raw).toUpperCase() }, raw);
        cell.append(badge);
      } else cell.textContent = column.format ? column.format(raw) : text(raw);
      tr.append(cell);
    }
    body.append(tr);
  }
  table.append(body);
  const tableWrap = element("div", { className: "table-wrap" });
  tableWrap.append(table);
  target.append(tableWrap);
}

function renderMetric(target, label, value, note = "") {
  const metric = element("article", { className: "metric" });
  metric.append(element("p", { className: "metric-label" }, label));
  metric.append(element("p", { className: "metric-value" }, value));
  if (note) metric.append(element("p", { className: "metric-note" }, note));
  target.append(metric);
}

function resourceError(key) {
  return dashboard.errors && dashboard.errors[key];
}

function renderStatus() {
  const status = dashboard.status;
  const target = $("#status-summary");
  clear(target);
  if (!status) {
    renderMessage(target, safeError(resourceError("status")), true);
    return;
  }
  const counts = status.counts || {};
  renderMetric(target, "Mode", status.mode);
  renderMetric(target, "Production acceptance", status.production_acceptance);
  renderMetric(target, "Database", status.database);
  renderMetric(target, "Leased active runs", number(status.active_leased_runs));
  renderMetric(target, "Campaigns", number(counts.campaigns));
  renderMetric(target, "Tasks", number(counts.tasks));
  renderMetric(target, "Artifacts", number(counts.artifacts));
  renderMetric(target, "Events", number(counts.events));
  $("#operator-role").textContent = status.role ? `Role: ${status.role}` : "Role unavailable";
  $("#as-of").textContent = status.as_of ? `Control-plane time: ${dateTime(status.as_of)}` : "Control-plane time unavailable";
  $("#incident-count").textContent = Array.isArray(dashboard.incidents) ? number(dashboard.incidents.length) : "—";
  renderTable($("#incidents-table"), [
    { label: "Incident", value: "incident_id" }, { label: "Severity", value: "severity", badge: true },
    { label: "Status", value: "status", badge: true }, { label: "Opened", value: "opened_at", format: dateTime },
    { label: "Updated", value: "updated_at", format: dateTime },
  ], dashboard.incidents, "No unresolved incidents are currently projected.", resourceError("incidents"));
}

function renderRuns() {
  renderTable($("#runs-table"), [
    { label: "Run", value: "run_id" }, { label: "Activity", value: "activity_state", badge: true },
    { label: "Task class", value: "task_class" }, { label: "Role", value: "agent_role_id" },
    { label: "Current action", value: "current_action" }, { label: "Why running", value: "why_running" },
    { label: "Heartbeat", value: "heartbeat_at", format: dateTime }, { label: "Lease expires", value: "lease_expires_at", format: dateTime },
    { label: "Retries", value: (row) => `${number(row.retry_count)} / ${number(row.max_retries)}` },
  ], dashboard.runs, "No active task runs are currently projected.", resourceError("runs"));
}

function renderQueues() {
  const queues = dashboard.queues;
  renderTable($("#queues-table"), [
    { label: "Task class", value: "task_class" }, { label: "Lane", value: "lane_class" },
    { label: "Status", value: "status", badge: true }, { label: "Count", value: "count", format: number },
    { label: "Oldest queued", value: "oldest_at", format: dateTime },
  ], queues && queues.queues, "No queued work is currently projected.", resourceError("queues"));
}

function renderCampaigns() {
  renderTable($("#campaigns-table"), [
    { label: "Campaign", value: "campaign_id" }, { label: "Purpose", value: "purpose" },
    { label: "Horizon", value: "horizon_at", format: dateTime }, { label: "USD budget", value: "usd_budget" },
    { label: "Allocated USD", value: "allocated_usd" }, { label: "Token budget", value: "token_budget", format: number },
    { label: "Statistical budget", value: "statistical_budget", format: number },
  ], dashboard.campaigns, "No campaigns are currently available to this role.", resourceError("campaigns"));
}

function renderPaper() {
  const paper = dashboard.paper || {};
  const status = dashboard.status || {};
  const mayStop = status.role === "owner" || status.role === "operator";
  $("#paper-stop-control").hidden = !mayStop;
  renderTable($("#paper-runs-table"), [
    { label: "Paper run", value: "paper_run_id" }, { label: "Status", value: "status", badge: true },
    { label: "Policy", value: "policy_version" }, { label: "Reporting currency", value: "reporting_currency" },
    { label: "Reconciled", value: "reconciled_at", format: dateTime }, { label: "Created", value: "created_at", format: dateTime },
  ], paper.runs, "No paper runs are currently projected.", resourceError("paper"));
  renderTable($("#paper-stops-table"), [
    { label: "Safety latch", value: "safety_latch_id" }, { label: "Scope", value: "scope_type", badge: true },
    { label: "Scope ID", value: "scope_id" }, { label: "Reason", value: "reason_code" },
    { label: "Initiated", value: (row) => row.automatic ? "Automatic" : "Manual" }, { label: "Created", value: "created_at", format: dateTime },
  ], paper.safety_latches, "No active global safety latches are currently projected.", resourceError("paper"));
  renderTable($("#orders-table"), [
    { label: "Order", value: "paper_order_id" }, { label: "Paper run", value: "paper_run_id" },
    { label: "Instrument", value: "instrument_id" }, { label: "Venue", value: "venue_id" },
    { label: "Side", value: "side", badge: true }, { label: "Type", value: "order_type" },
    { label: "Price", value: "price" }, { label: "Quantity", value: "quantity" }, { label: "Filled", value: "filled_quantity" },
    { label: "State", value: "final_state", badge: true }, { label: "Updated", value: "updated_at", format: dateTime },
  ], dashboard.orders, "No paper orders are currently projected.", resourceError("orders"));
  renderTable($("#reservations-table"), [
    { label: "Reservation", value: "reservation_id" }, { label: "Paper run", value: "paper_run_id" },
    { label: "Pool", value: "pool_id" }, { label: "Envelope", value: "envelope_version" },
    { label: "Original", value: "original_amount" }, { label: "Working", value: "working_amount" },
    { label: "Position", value: "position_amount" }, { label: "State", value: "state", badge: true },
    { label: "Expires", value: "expires_at", format: dateTime },
  ], dashboard.reservations, "No risk reservations are currently projected.", resourceError("reservations"));
}

function renderGovernance() {
  renderTable($("#governance-table"), [
    { label: "Proposal", value: "proposal_id" }, { label: "Version", value: "proposal_version", format: number },
    { label: "Status", value: "status", badge: true },
    { label: "Classification", value: (row) => typeof row.classification === "string" ? row.classification : "Structured classification" },
    { label: "Approval snapshot", value: "approval_snapshot_hash" }, { label: "Created", value: "created_at", format: dateTime },
    { label: "Updated", value: "updated_at", format: dateTime },
  ], dashboard.governance, "No governance proposals are currently available to this role.", resourceError("governance"));
}

function renderRequirements() {
  const requirements = dashboard.requirements;
  const summary = $("#requirements-summary");
  clear(summary);
  if (!requirements) {
    renderMessage(summary, safeError(resourceError("requirements")), true);
    renderMessage($("#requirements-table"), "Requirements data is unavailable.", true);
    return;
  }
  renderMetric(summary, "SRS version", requirements.srs_version);
  renderMetric(summary, "Tracked requirements", number(requirements.total));
  for (const [state, count] of Object.entries(requirements.counts || {})) renderMetric(summary, state, number(count));
  renderTable($("#requirements-table"), [
    { label: "Requirement", value: "requirement_id" }, { label: "Source", value: "source_anchor" },
    { label: "Status", value: "status", badge: true }, { label: "Owning module", value: "owning_module" },
    { label: "Implementation references", value: (row) => Array.isArray(row.implementation_refs) ? row.implementation_refs.join(", ") : "—" },
    { label: "Test references", value: (row) => Array.isArray(row.test_refs) ? row.test_refs.join(", ") : "—" },
  ], requirements.requirements, "No requirements were returned by the traceability registry.");
}

function renderAll() {
  renderStatus();
  renderRuns();
  renderQueues();
  renderCampaigns();
  renderPaper();
  renderGovernance();
  renderRequirements();
}

async function loadDashboard() {
  const version = sessionVersion;
  const entries = Object.entries(endpoints);
  const results = await Promise.allSettled(entries.map(([, path]) => request(path)));
  if (version !== sessionVersion || !accessToken) return null;
  dashboard = { errors: {} };
  results.forEach((result, index) => {
    const [key] = entries[index];
    if (result.status === "fulfilled") dashboard[key] = result.value;
    else dashboard.errors[key] = result.reason;
  });
  renderAll();
  return dashboard;
}

async function authenticate(event) {
  event.preventDefault();
  if (!accessTokenInput.value) return;
  authFeedback.textContent = "Connecting…";
  const version = ++sessionVersion;
  const button = authForm.querySelector('button[type="submit"]');
  button.disabled = true;
  accessToken = accessTokenInput.value;
  try {
    const status = await request(endpoints.status);
    if (version !== sessionVersion) return;
    accessTokenInput.value = "";
    dashboard = { status, errors: {} };
    authPanel.hidden = true;
    consoleElement.hidden = false;
    $("#connection-state").textContent = "Connected; loading authenticated operational data";
    const loaded = await loadDashboard();
    if (!loaded) return;
    const failed = Object.keys(loaded.errors).length;
    $("#connection-state").textContent = failed ? "Connected with unavailable projections" : "Connected to authenticated control plane";
    refreshFeedback.className = "feedback info";
    refreshFeedback.textContent = failed ? `${failed} projection${failed === 1 ? "" : "s"} could not be loaded. Individual views show why.` : "All dashboard projections loaded.";
  } catch (error) {
    if (version !== sessionVersion) return;
    signOut();
    accessToken = null;
    accessTokenInput.value = "";
    authFeedback.textContent = safeError(error);
  } finally {
    button.disabled = false;
  }
}

async function refreshDashboard() {
  const button = $("#refresh");
  button.disabled = true;
  refreshFeedback.className = "feedback info";
  refreshFeedback.textContent = "Refreshing authenticated operational projections…";
  try {
    const loaded = await loadDashboard();
    if (!loaded) return;
    const failed = Object.keys(loaded.errors).length;
    $("#connection-state").textContent = failed ? "Connected with unavailable projections" : "Connected to authenticated control plane";
    refreshFeedback.textContent = failed ? `${failed} projection${failed === 1 ? "" : "s"} could not be refreshed. Individual views show why.` : "All dashboard projections refreshed.";
    if (loaded.errors.status && loaded.errors.status.status === 401) signOut();
  } finally {
    button.disabled = false;
  }
}

function signOut() {
  sessionVersion += 1;
  accessToken = null;
  dashboard = {};
  pendingStop = null;
  authForm.reset();
  authFeedback.textContent = "";
  refreshFeedback.textContent = "";
  consoleElement.hidden = true;
  authPanel.hidden = false;
  emergencyStopDialog.close();
  for (const node of consoleElement.querySelectorAll('[id$="-table"], [id$="-summary"]')) clear(node);
  $("#operator-role").textContent = "";
  $("#as-of").textContent = "";
}

function randomIdempotencyKey() {
  if (crypto.randomUUID) return crypto.randomUUID();
  const bytes = new Uint8Array(16);
  crypto.getRandomValues(bytes);
  return Array.from(bytes, (value) => value.toString(16).padStart(2, "0")).join("");
}

function openEmergencyStop() {
  $("#emergency-stop-form").reset();
  $("#stop-feedback").textContent = "";
  emergencyStopDialog.showModal();
}

async function requestEmergencyStop(event) {
  event.preventDefault();
  const submit = $("#submit-emergency-stop");
  const feedback = $("#stop-feedback");
  submit.disabled = true;
  feedback.textContent = "Submitting safety request…";
  const reason = $("#stop-reason").value;
  if (!pendingStop || pendingStop.reason !== reason) {
    pendingStop = { reason, key: randomIdempotencyKey() };
  }
  try {
    const result = await request("/paper/emergency-stop", {
      method: "POST",
      headers: { "Content-Type": "application/json", "Idempotency-Key": pendingStop.key },
      body: JSON.stringify({ reason }),
    });
    feedback.textContent = `Emergency stop recorded: ${text(result.stop_id)}.`;
    await refreshDashboard();
    emergencyStopDialog.close();
    refreshFeedback.className = "feedback info";
    refreshFeedback.textContent = "Emergency stop request completed. Paper projections were refreshed.";
  } catch (error) {
    feedback.textContent = safeError(error);
  } finally {
    submit.disabled = false;
  }
}

function activateView(view) {
  for (const button of document.querySelectorAll("[data-view]")) {
    const active = button.dataset.view === view;
    button.setAttribute("aria-selected", String(active));
    button.tabIndex = active ? 0 : -1;
    $("#view-" + button.dataset.view).hidden = !active;
  }
}

authForm.addEventListener("submit", authenticate);
$("#refresh").addEventListener("click", refreshDashboard);
$("#sign-out").addEventListener("click", signOut);
$("#open-emergency-stop").addEventListener("click", openEmergencyStop);
$("#cancel-emergency-stop").addEventListener("click", () => emergencyStopDialog.close());
$("#emergency-stop-form").addEventListener("submit", requestEmergencyStop);
const viewButtons = Array.from(document.querySelectorAll("[data-view]"));
viewButtons.forEach((button, index) => {
  button.tabIndex = index === 0 ? 0 : -1;
  button.addEventListener("click", () => activateView(button.dataset.view));
  button.addEventListener("keydown", (event) => {
    if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
    event.preventDefault();
    let next = index;
    if (event.key === 'ArrowLeft') next = (index - 1 + viewButtons.length) % viewButtons.length;
    if (event.key === 'ArrowRight') next = (index + 1) % viewButtons.length;
    if (event.key === 'Home') next = 0;
    if (event.key === 'End') next = viewButtons.length - 1;
    const nextButton = viewButtons[next];
    activateView(nextButton.dataset.view);
    nextButton.focus();
  });
});

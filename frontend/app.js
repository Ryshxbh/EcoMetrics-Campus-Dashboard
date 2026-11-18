const $ = (selector) => document.querySelector(selector);
const number = new Intl.NumberFormat("en-IN", { maximumFractionDigits: 1 });
const compact = new Intl.NumberFormat("en-IN", { notation: "compact", maximumFractionDigits: 1 });
const dateText = new Intl.DateTimeFormat("en-IN", { day: "numeric", month: "short", year: "numeric" });
const state = { start: "", end: "", building: "", grain: "month" };
const viewCopy = {
  overview: ["OVERVIEW", "Campus energy, at a glance", "Explore measured electricity use across seven building groups at IIIT-Delhi."],
  activity: ["OPERATING PROFILE", "Read the rhythm of the campus", "See how electricity use shifts with time and the academic calendar."],
  quality: ["DATA QUALITY", "Check the readings behind the totals", "Find gaps and unusual intervals before using a number in a decision."]
};

function esc(value) {
  return String(value ?? "").replace(/[&<>"']/g, (character) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[character]);
}
function fmt(value, digits = 1) {
  return value == null || !Number.isFinite(Number(value)) ? "—" : new Intl.NumberFormat("en-IN", { maximumFractionDigits: digits }).format(Number(value));
}
function pctClass(value) {
  const bucket = Math.min(100, Math.max(0, Math.round((Number(value) || 0) / 5) * 5));
  return `pct-${bucket}`;
}
function fmtDate(value) {
  if (!value) return "—";
  const [year, month, day] = value.slice(0, 10).split("-").map(Number);
  return dateText.format(new Date(year, month - 1, day));
}
function qs(extra = {}) {
  const params = new URLSearchParams({ start_date: state.start, end_date: state.end, ...extra });
  if (state.building) params.set("building_code", state.building);
  return params.toString();
}
async function get(path, extra = {}) {
  const response = await fetch(`/api/${path}?${qs(extra)}`, { headers: { Accept: "application/json" } });
  if (!response.ok) {
    let message = `Request failed (${response.status})`;
    try { message = (await response.json()).detail || message; } catch { /* keep the HTTP status */ }
    throw new Error(message);
  }
  return response.json();
}
function setStatus(message = "", kind = "") {
  const node = $("#global-status");
  node.textContent = message;
  node.className = `global-status ${kind}`.trim();
}
function setWindowLabel(start, end) {
  $("#data-window").innerHTML = `<span class="window-dot"></span><span>${esc(fmtDate(start))} — ${esc(fmtDate(end))} <b>·</b> Asia/Kolkata</span>`;
}
function setNav(view) {
  document.querySelectorAll("[data-view-target]").forEach((button) => button.classList.toggle("active", button.dataset.viewTarget === view));
  document.querySelectorAll("[data-view]").forEach((panel) => { panel.hidden = panel.dataset.view !== view; });
  const copy = viewCopy[view] || viewCopy.overview;
  $("#crumb-current").textContent = copy[0];
  $("#page-title").textContent = copy[1];
  $("#page-copy").textContent = copy[2];
  history.replaceState(null, "", `#${view}`);
}
function asKwh(value) { return value == null ? "—" : `${compact.format(value)} kWh`; }
function metricChange(value) {
  if (value == null) return "No prior period";
  const arrow = value > 0 ? "↑" : value < 0 ? "↓" : "→";
  const cls = value > 0 ? "trend-up" : value < 0 ? "trend-down" : "trend-flat";
  return `<span class="${cls}">${arrow} ${fmt(Math.abs(value))}%</span> vs prior window`;
}
function renderOverview(data) {
  $("#metric-energy").textContent = compact.format(data.electricity_kwh);
  $("#metric-change").innerHTML = metricChange(data.change_vs_previous_pct);
  $("#metric-carbon").textContent = `${compact.format(data.estimated_co2_kg)} kg`;
  $("#metric-coverage").textContent = `${fmt(data.usable_hour_pct)}%`;
  $("#metric-coverage-label").textContent = `${number.format(data.usable_hours)} of ${number.format(data.expected_hours)} hours`;
  $("#metric-night").textContent = "—";
  $("#metric-night-label").textContent = "Review in operating profile";
}
function lineChart(target, points) {
  if (!points.length || points.every((point) => point.energy_kwh == null)) {
    target.innerHTML = '<div class="empty-state">There are no usable readings in this window. Try a different date range.</div>';
    return;
  }
  const width = 720, height = 260, left = 58, right = 18, top = 20, bottom = 44;
  const values = points.map((point) => point.energy_kwh).filter((value) => value != null);
  const max = Math.max(1, ...values) * 1.08;
  const plotW = width - left - right, plotH = height - top - bottom;
  const x = (index) => left + (points.length === 1 ? plotW / 2 : index * plotW / (points.length - 1));
  const y = (value) => top + plotH - value / max * plotH;
  const guides = [0, 0.5, 1].map((ratio) => {
    const yy = top + plotH * ratio;
    return `<line x1="${left}" y1="${yy}" x2="${width - right}" y2="${yy}" class="chart-grid"/><text x="${left - 10}" y="${yy + 4}" text-anchor="end" class="chart-axis-label">${compact.format(max * (1 - ratio))}</text>`;
  }).join("");
  const segments = [];
  let active = [];
  points.forEach((point, index) => {
    if (point.energy_kwh == null) {
      if (active.length) segments.push(active);
      active = [];
    } else active.push(`${x(index)},${y(point.energy_kwh)}`);
  });
  if (active.length) segments.push(active);
  const paths = segments.map((segment) => `<polyline points="${segment.join(" ")}" class="chart-line"/>`).join("");
  const dots = points.map((point, index) => point.energy_kwh == null ? "" : `<circle cx="${x(index)}" cy="${y(point.energy_kwh)}" r="3.7" class="chart-dot"><title>${esc(fmtDate(point.period))}: ${esc(fmt(point.energy_kwh))} kWh · ${esc(fmt(point.coverage_pct))}% average meter coverage</title></circle>`).join("");
  const step = Math.max(1, Math.ceil(points.length / 6));
  const labels = points.map((point, index) => index % step === 0 || index === points.length - 1 ? `<text x="${x(index)}" y="${height - 12}" text-anchor="middle" class="chart-axis-label">${esc(shortPeriod(point.period))}</text>` : "").join("");
  target.innerHTML = `<svg viewBox="0 0 ${width} ${height}" preserveAspectRatio="none" aria-hidden="true">${guides}${paths}${dots}${labels}</svg>`;
}
function shortPeriod(value) {
  const [year, month, day] = value.split("-").map(Number);
  if (day && day !== 1) return `${day} ${new Intl.DateTimeFormat("en", { month: "short" }).format(new Date(year, month - 1, day))}`;
  return new Intl.DateTimeFormat("en", { month: "short", year: "2-digit" }).format(new Date(year, month - 1, 1));
}
function renderBuildingBars(buildings) {
  const sorted = [...buildings].sort((a, b) => b.energy_kwh - a.energy_kwh);
  const max = Math.max(1, ...sorted.map((item) => item.energy_kwh));
  $("#building-bars").innerHTML = sorted.map((item, index) => `<div class="bar-row"><div class="bar-row-label"><span>${esc(item.building_name)}</span><strong>${compact.format(item.energy_kwh)} <small>kWh</small></strong></div><div class="bar-track"><span class="bar-fill ${index === 0 ? "bar-fill-lead" : ""} ${pctClass(item.energy_kwh / max * 100)}"></span></div></div>`).join("");
}
function renderBenchmarks(buildings) {
  $("#benchmark-table").innerHTML = buildings.map((item) => `<tr><td><strong>${esc(item.building_name)}</strong><span class="table-subline">${esc(item.building_code)}</span></td><td>${esc(item.building_type)}</td><td class="numeric">${fmt(item.area_m2)} m²</td><td class="numeric">${number.format(item.energy_kwh)} kWh</td><td class="numeric"><strong>${fmt(item.energy_kwh_per_m2, 3)}</strong></td><td class="numeric">${fmt(item.coverage_pct)}%</td><td class="numeric">${number.format(item.estimated_co2_kg)} kg</td></tr>`).join("") || '<tr><td colspan="7" class="loading-cell">No building rows in this selection.</td></tr>';
}
function renderHourly(data) {
  const points = data.hourly_profile || [];
  const target = $("#hourly-chart");
  if (!points.length) { target.innerHTML = '<div class="empty-state">No hourly profile is available for this selection.</div>'; return; }
  const width = 720, height = 285, left = 48, right = 16, top = 18, bottom = 38;
  const max = Math.max(1, ...points.map((item) => item.average_power_kw || 0)) * 1.1;
  const plotH = height - top - bottom, plotW = width - left - right;
  const x = (hour) => left + hour / 23 * plotW;
  const y = (value) => top + plotH - value / max * plotH;
  const guides = [0, 0.5, 1].map((ratio) => { const yy = top + ratio * plotH; return `<line x1="${left}" y1="${yy}" x2="${width - right}" y2="${yy}" class="chart-grid"/><text x="${left - 9}" y="${yy + 4}" text-anchor="end" class="chart-axis-label">${compact.format(max * (1 - ratio))}</text>`; }).join("");
  const shadeX = x(22), shadeEnd = x(6);
  const nightShading = `<rect x="${left}" y="${top}" width="${shadeEnd - left}" height="${plotH}" class="night-shade"/><rect x="${shadeX}" y="${top}" width="${width - right - shadeX}" height="${plotH}" class="night-shade"/>`;
  const line = points.map((item) => `${x(item.hour)},${y(item.average_power_kw || 0)}`).join(" ");
  const dots = points.map((item) => `<circle cx="${x(item.hour)}" cy="${y(item.average_power_kw || 0)}" r="3.4" class="chart-dot chart-dot-copper"><title>${String(item.hour).padStart(2, "0")}:00 · ${fmt(item.average_power_kw)} kW mean load</title></circle>`).join("");
  const labels = [0, 4, 8, 12, 16, 20, 23].map((hour) => `<text x="${x(hour)}" y="${height - 10}" text-anchor="middle" class="chart-axis-label">${String(hour).padStart(2, "0")}:00</text>`).join("");
  target.innerHTML = `<svg viewBox="0 0 ${width} ${height}" preserveAspectRatio="none" aria-hidden="true">${nightShading}${guides}<polyline points="${line}" class="chart-line chart-line-copper"/>${dots}${labels}</svg>`;
}
function renderComparisons(data) {
  const max = Math.max(1, ...(data.calendar_comparison || []).map((item) => item.mean_daily_kwh || 0));
  $("#calendar-comparison").innerHTML = (data.calendar_comparison || []).map((item) => `<div class="comparison-row"><div><span class="activity-pill ${item.activity_level === "H" ? "activity-high" : item.activity_level === "L" ? "activity-low" : ""}">${item.activity_level === "H" ? "High activity" : item.activity_level === "L" ? "Low activity" : "Other / unknown"}</span><small>${item.days} days</small></div><strong>${compact.format(item.mean_daily_kwh)} <small>kWh/day</small></strong><div class="comparison-track"><span class="${pctClass((item.mean_daily_kwh || 0) / max * 100)}"></span></div></div>`).join("") || '<p class="empty-state">No calendar-linked days in this selection.</p>';
  $("#working-comparison").innerHTML = (data.working_day_comparison || []).map((item) => `<div class="working-stat"><strong>${compact.format(item.mean_daily_kwh)}</strong><span>kWh/day</span><small>${esc(item.day_type)} · ${item.days} days</small></div>`).join("") || '<p class="empty-state">No working-day comparison available.</p>';
  $("#schedule-note").textContent = data.schedule_note;
}
function renderOpportunities(data) {
  const buildings = data.buildings || [];
  const sumNight = buildings.reduce((sum, item) => sum + (item.night_kwh || 0), 0);
  const allEnergy = window.dashboardEnergy || 0;
  $("#activity-night-total").textContent = `${compact.format(sumNight)} kWh`;
  if (allEnergy > 0) {
    const share = Math.min(100, Math.max(0, sumNight / allEnergy * 100));
    $("#metric-night").textContent = `${fmt(share)}%`;
    $("#metric-night-label").textContent = "of electricity in the selected window";
  }
  $("#opportunities").innerHTML = buildings.map((item) => `<article class="opportunity-card"><div class="opportunity-head"><span class="opportunity-icon" aria-hidden="true">${item.building_type === "residential" ? "⌂" : "◷"}</span><span class="quiet-label">${esc(item.building_type)}</span></div><h3>${esc(item.building_name)}</h3><p>${esc(item.review_note)}</p><div class="opportunity-metrics"><div><span>Night load</span><strong>${fmt(item.night_to_day_pct)}<small>${item.night_to_day_pct == null ? "" : "% of day"}</small></strong></div><div><span>Night energy</span><strong>${compact.format(item.night_kwh)}<small>kWh</small></strong></div></div></article>`).join("") || '<p class="empty-state">No operating-profile readings for this selection.</p>';
}
function renderQuality(data) {
  $("#quality-usable").textContent = `${fmt(data.usable_hour_pct)}%`;
  $("#quality-partial").textContent = number.format(data.partial_hours);
  $("#quality-missing").textContent = number.format(data.missing_hours);
  $("#quality-spikes").textContent = number.format(data.statistical_spikes);
  $("#nav-quality-count").textContent = number.format(data.partial_hours + data.missing_hours + data.statistical_spikes);
  $("#quality-buildings").innerHTML = data.buildings.map((item) => `<div class="quality-building"><div class="quality-building-name"><strong>${esc(item.building_name)}</strong><span class="quality-status status-${esc(item.status)}">${esc(item.status)}</span></div><div class="quality-meter"><span class="quality-meter-fill fill-${esc(item.status)} ${pctClass(item.usable_hour_pct)}"></span></div><div class="quality-building-foot"><span>${fmt(item.usable_hour_pct)}% usable hours</span><span>${fmt(item.coverage_pct)}% average samples/hour</span></div></div>`).join("");
  $("#quality-events").innerHTML = data.events.map((item) => `<tr><td>${esc(fmtDate(item.observed_at))}<span class="table-subline">${esc(String(item.observed_at).slice(11, 16))} local</span></td><td><strong>${esc(item.building_name)}</strong></td><td class="numeric">${item.average_power_kw == null ? "—" : `${fmt(item.average_power_kw)} kW`}</td><td class="numeric">${fmt(item.coverage_pct)}%</td><td><span class="event-tag ${item.spike_flag ? "event-spike" : "event-gap"}">${item.spike_flag ? "Spike to review" : esc(item.quality_flag)}</span></td></tr>`).join("") || '<tr><td colspan="5" class="loading-cell">No flagged intervals in this selection.</td></tr>';
  $("#event-window-label").textContent = `${number.format(data.events.length)} of ${number.format(data.flagged_rows)} flagged intervals shown`;
  $("#quality-method").textContent = data.method_note;
  $("#export-quality").href = `/api/quality/export.csv?${qs()}`;
}
async function refresh() {
  setStatus("Updating the selected date window…", "loading");
  setWindowLabel(state.start, state.end);
  try {
    const [overview, trends, benchmarks, activity, opportunities, quality] = await Promise.all([
      get("overview"), get("trends", { grain: state.grain }), get("benchmarks"), get("activity"), get("opportunities"), get("quality")
    ]);
    window.dashboardEnergy = overview.electricity_kwh;
    renderOverview(overview);
    renderBenchmarks(benchmarks.buildings);
    renderBuildingBars(benchmarks.buildings);
    lineChart($("#trend-chart"), trends.points);
    $("#trend-subtitle").textContent = `${state.grain === "month" ? "Monthly" : "Daily"} electricity · selected date window`;
    renderHourly(activity);
    renderComparisons(activity);
    renderOpportunities(opportunities);
    renderQuality(quality);
    setStatus(`Showing ${number.format(overview.usable_hours)} usable hourly readings. Emissions use the CEA factor shown on the page.`, "success");
  } catch (error) {
    setStatus(`${error.message}. Confirm the services are healthy, then refresh.`, "error");
  }
}
async function initialize() {
  try {
    const filters = await (await fetch("/api/filters")).json();
    const start = filters.start_date, end = filters.end_date;
    const building = $("#building-filter");
    building.insertAdjacentHTML("beforeend", filters.buildings.map((item) => `<option value="${esc(item.building_code)}">${esc(item.building_name)}</option>`).join(""));
    const endDate = new Date(Number(end.slice(0, 4)), Number(end.slice(5, 7)) - 1, Number(end.slice(8, 10)));
    const startDate = new Date(endDate);
    startDate.setDate(startDate.getDate() - 89);
    const lowerBound = new Date(Number(start.slice(0, 4)), Number(start.slice(5, 7)) - 1, Number(start.slice(8, 10)));
    const defaultStart = startDate < lowerBound ? start : `${startDate.getFullYear()}-${String(startDate.getMonth() + 1).padStart(2, "0")}-${String(startDate.getDate()).padStart(2, "0")}`;
    state.start = defaultStart; state.end = end;
    $("#start-date").min = start; $("#start-date").max = end; $("#start-date").value = state.start;
    $("#end-date").min = start; $("#end-date").max = end; $("#end-date").value = state.end;
    setWindowLabel(state.start, state.end);
    await refresh();
  } catch (error) {
    setStatus(`Could not load dashboard filters: ${error.message}. Check service health and refresh.`, "error");
  }
}

document.querySelectorAll("[data-view-target]").forEach((button) => button.addEventListener("click", () => setNav(button.dataset.viewTarget)));
$("#filters-form").addEventListener("submit", (event) => {
  event.preventDefault();
  state.start = $("#start-date").value;
  state.end = $("#end-date").value;
  state.building = $("#building-filter").value;
  if (state.start > state.end) { setStatus("The start date must be on or before the end date.", "error"); return; }
  refresh();
});
$("#trend-grain").addEventListener("change", (event) => { state.grain = event.target.value; refresh(); });
const initialView = location.hash.slice(1);
setNav(viewCopy[initialView] ? initialView : "overview");
initialize();

"use strict";
const $ = id => document.getElementById(id);
let snapshot = null, busy = false, map = null, layers = null, visibleRows = [], mapSignature = "";
const routeLayers = new Map();
const fullscreenBackground = new Map();
const speed = v => Number.isFinite(v) ? `${v.toLocaleString("it-IT", {minimumFractionDigits: 1, maximumFractionDigits: 1})} km/h` : "—";
const date = v => v ? new Date(v.slice(0, 10) + "T12:00:00").toLocaleDateString("it-IT", {day: "2-digit", month: "short", year: "numeric"}) : "—";
const time = v => {
  const s = Math.round(v);
  return s >= 3600 ? `${Math.floor(s / 3600)}:${String(Math.floor(s % 3600 / 60)).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}` : `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
};
function el(tag, text = "", className = "") {
  const node = document.createElement(tag); node.textContent = text; node.className = className; return node;
}
function link(text, url) {const a = el("a", text); a.href = url; a.target = "_blank"; a.rel = "noopener"; return a;}
function notice(text, error = false) {$("notice").hidden = false; $("notice").textContent = text; $("notice").className = error ? "error" : "";}
async function api(path, method = "GET") {
  const response = await fetch(path, {method}); const data = await response.json();
  if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : "Aggiornamento non riuscito.");
  return data;
}
function options(id, values, label) {
  const selected = $(id).value;
  $(id).replaceChildren(el("option", label), ...Array.from(new Set(values)).sort((a, b) => a.localeCompare(b, "it")).map(v => {const o = el("option", v); o.value = v; return o;}));
  $(id).options[0].value = ""; if (values.includes(selected)) $(id).value = selected;
}
function filters() {
  const rows = snapshot?.rows || [];
  options("country-filter", rows.map(r => r.country), "Tutti i paesi");
  const countries = rows.filter(r => !$("country-filter").value || r.country === $("country-filter").value);
  options("region-filter", countries.map(r => r.region), "Tutte le regioni");
  const regions = countries.filter(r => !$("region-filter").value || r.region === $("region-filter").value);
  options("zone-filter", regions.map(r => r.zone).filter(Boolean), "Tutte le zone");
}
function profile(points) {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", "0 0 500 110"); svg.setAttribute("role", "img"); svg.setAttribute("aria-label", "Profilo altimetrico Garmin del miglior passaggio"); svg.classList.add("climb-profile");
  if (!points?.length) return svg;
  const low = Math.min(...points.map(p => p[1])), high = Math.max(...points.map(p => p[1])), xMax = Math.max(...points.map(p => p[0]), 1);
  const line = document.createElementNS("http://www.w3.org/2000/svg", "polyline");
  line.setAttribute("points", points.map(p => `${10 + p[0] / xMax * 480},${100 - (p[1] - low) / Math.max(high - low, 1) * 90}`).join(" "));
  line.setAttribute("fill", "none"); line.setAttribute("stroke", "#79e4c2"); line.setAttribute("stroke-width", "2"); svg.append(line); return svg;
}
function gpsQuality(attempt) {
  return attempt.gps_tolerance_used ? `GPS parziale · ${Math.round(attempt.gps_coverage_pct)}% di corrispondenza · tempo stimato` : "";
}
function mapDetails(row, popup = false) {
  const box = el("div", "", "map-climb-detail");
  box.append(el("strong", row.name), el("div", `${row.zone} · ${row.region}`, "map-place"));
  const stats = el("div", "", "map-detail-stats");
  stats.append(el("span", `${(row.distance_m / 1000).toFixed(2)} km`), el("span", `+${Math.round(row.gain_m)} m`), el("span", `${row.grade_pct.toFixed(1)}% medio`));
  box.append(stats, el("div", `Quota di arrivo: ${Math.round(row.summit_m)} m`, "map-place"), profile(row.profile));
  const best = el("div", "", "map-best"); best.append(el("strong", time(row.best.duration_s)), el("span", `Miglior tempo · ${date(row.best.date)}`));
  box.append(best, el("div", `Velocità media: ${speed(row.best.avg_speed_kmh)}`, "map-speed"), el("div", `${row.attempt_count} ${row.attempt_count === 1 ? "passaggio" : "passaggi"} · soste incluse`, "map-place"));
  if (row.best.gps_tolerance_used) box.append(el("div", gpsQuality(row.best), "map-place"));
  if (row.aliases?.length) box.append(el("div", row.aliases.join(" · "), "map-place"));
  if (popup) {const links = el("div", "", "map-links"); links.append(link("Attività Garmin ↗", row.best.garmin_url), link("Climbfinder ↗", row.source_url)); box.append(links);}
  return box;
}
function initMap() {
  if (map || !window.L) return;
  map = L.map("climb-map", {scrollWheelZoom: true}).setView([43, 11], 5);
  L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {maxZoom: 18, attribution: '&copy; <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">OpenStreetMap contributors</a>'}).addTo(map).on("tileerror", () => {$("map-hint").textContent = "Sfondo cartografico non disponibile. I percorsi e i dettagli delle salite restano consultabili.";});
  layers = L.featureGroup().addTo(map);
}
function syncMapFullscreen() {
  const expanded = $("map-panel").classList.contains("map-expanded");
  $("fullscreen-map").textContent = expanded ? "⛶ Esci da schermo intero" : "⛶ Schermo intero";
  $("fullscreen-map").setAttribute("aria-pressed", String(expanded));
  requestAnimationFrame(() => {
    map?.invalidateSize({animate: false});
    map?.eachLayer(layer => {if (layer instanceof L.Popup) layer.update();});
  });
}
function setMapFullscreen(expanded) {
  const panel = $("map-panel");
  panel.classList.toggle("map-expanded", expanded);
  document.body.classList.toggle("map-expanded-open", expanded);
  if (expanded) {
    panel.setAttribute("role", "dialog"); panel.setAttribute("aria-modal", "true");
    for (const node of [...document.querySelectorAll("main > :not(#map-panel)"), document.querySelector(".sidebar")]) {
      if (node) {fullscreenBackground.set(node, node.inert); node.inert = true;}
    }
  } else {
    panel.removeAttribute("role"); panel.removeAttribute("aria-modal");
    fullscreenBackground.forEach((inert, node) => {node.inert = inert;}); fullscreenBackground.clear();
    $("fullscreen-map").focus({preventScroll: true});
  }
  syncMapFullscreen();
}
function toggleMapFullscreen() {setMapFullscreen(!$("map-panel").classList.contains("map-expanded"));}
document.addEventListener("keydown", event => {
  if (!$("map-panel").classList.contains("map-expanded")) return;
  if (event.key === "Escape") {event.preventDefault(); setMapFullscreen(false);}
  if (event.key === "Tab") {
    const controls = Array.from($("map-panel").querySelectorAll('a[href],button:not(:disabled),input,select,[tabindex="0"]'));
    const first = controls[0], last = controls.at(-1);
    if (event.shiftKey && document.activeElement === first) {event.preventDefault(); last?.focus();}
    else if (!event.shiftKey && document.activeElement === last) {event.preventDefault(); first?.focus();}
  }
});
function fitMap() {if (map && visibleRows.length) map.fitBounds(layers.getBounds(), {padding: [30, 30], maxZoom: 13});}
function showOnMap(row) {
  if (!map) return;
  const line = routeLayers.get(row.id);
  map.fitBounds(line.getBounds(), {padding: [50, 50], maxZoom: 14, animate: false});
  line.openPopup(L.latLng(row.path[Math.floor(row.path.length / 2)]));
  $("climb-map").scrollIntoView({behavior: "smooth", block: "center"});
}
function renderMap(rows) {
  initMap(); if (!map) return;
  const signature = `${snapshot.generated_at}|${rows.map(r => r.id).join(",")}`;
  if (signature === mapSignature) return;
  mapSignature = signature; visibleRows = rows; map.closePopup(); routeLayers.forEach(line => line.closeTooltip()); layers.clearLayers(); routeLayers.clear();
  $("map-empty").hidden = rows.length > 0; $("fit-map").disabled = rows.length === 0;
  rows.forEach(row => {
    const color = row.attempt_count >= 4 ? "#ff7199" : row.attempt_count >= 2 ? "#ffbe68" : "#79e4c2";
    L.polyline(row.path, {color, weight: 19, opacity: 0.2, interactive: false}).addTo(layers);
    const line = L.polyline(row.path, {color, weight: 5, opacity: 1, className: "heat-route"}).addTo(layers);
    line.bindTooltip(mapDetails(row), {sticky: true, className: "climb-tooltip", direction: "auto"});
    line.bindPopup(mapDetails(row, true), {className: "climb-popup", maxWidth: 310, minWidth: 235});
    line.on("mouseover", () => line.setStyle({weight: 8})).on("mouseout", () => line.setStyle({weight: 5}));
    const path = line.getElement();
    if (path) {
      path.setAttribute("tabindex", "0"); path.setAttribute("role", "button"); path.setAttribute("aria-label", `Dettagli ${row.name}`);
      path.addEventListener("keydown", event => {if (event.key === "Enter" || event.key === " ") {event.preventDefault(); showOnMap(row);}});
      path.addEventListener("focus", () => line.openTooltip(L.latLng(row.path[Math.floor(row.path.length / 2)])));
      path.addEventListener("blur", () => line.closeTooltip());
    }
    routeLayers.set(row.id, line);
  }); fitMap();
}
function details(row) {
  const box = el("details", "", "climb-details"); box.append(el("summary", `Tentativi e profilo · ${row.attempt_count}`));
  box.append(profile(row.profile), el("p", `Quota di arrivo del catalogo: ${Math.round(row.summit_m)} m · Profilo Garmin del miglior passaggio.`, "small muted"));
  const list = el("div", "", "attempt-list");
  row.attempts.forEach((attempt, i) => {const item = el("p"); item.append(link(`${i === 0 ? "★ " : ""}${time(attempt.duration_s)} · ${speed(attempt.avg_speed_kmh)} · ${date(attempt.date)} · ${attempt.activity_name} ↗`, attempt.garmin_url)); if (attempt.gps_tolerance_used) item.append(el("span", ` · ${gpsQuality(attempt)}`, "small muted")); list.append(item);});
  box.append(list); return box;
}
function renderGroups() {
  if (!snapshot) return;
  const query = $("search").value.trim().toLocaleLowerCase("it");
  const rows = snapshot.rows.filter(r => (!$("country-filter").value || r.country === $("country-filter").value) && (!$("region-filter").value || r.region === $("region-filter").value) && (!$("zone-filter").value || r.zone === $("zone-filter").value) && `${r.name} ${(r.aliases || []).join(" ")} ${r.zone} ${r.region}`.toLocaleLowerCase("it").includes(query));
  renderMap(rows);
  const groups = new Map(); rows.forEach(row => {const key = `${row.country} · ${row.region}`; if (!groups.has(key)) groups.set(key, []); groups.get(key).push(row);});
  const nodes = [];
  groups.forEach((items, title) => {
    const card = el("section", "", "card"), heading = el("div", "", "section-heading");
    heading.append(el("h2", title), el("span", `${items.length} ${items.length === 1 ? "salita" : "salite"}`, "badge")); card.append(heading);
    items.forEach(row => {
      const article = el("article", "", "climb-row"), head = el("div", "", "section-heading"), label = el("div");
      label.append(el("h3", row.name), el("p", [row.zone, ...(row.aliases || [])].join(" · "), "small muted"));
      const locate = el("button", "Sulla mappa", "subtle"); locate.setAttribute("aria-label", `Mostra ${row.name} sulla mappa`); locate.onclick = () => showOnMap(row);
      head.append(label, locate); const stats = el("div", "", "climb-stats");
      stats.append(el("strong", time(row.best.duration_s), "best-time"), el("span", `Media ${speed(row.best.avg_speed_kmh)}`, "climb-speed"), el("span", `${(row.distance_m / 1000).toFixed(2)} km`), el("span", `+${Math.round(row.gain_m)} m`), el("span", `${row.grade_pct.toFixed(1)}% medio`), el("span", date(row.best.date)), link("Miglior passaggio Garmin ↗", row.best.garmin_url), link("Climbfinder ↗", row.source_url));
      article.append(head, stats);
      if (row.best.gps_tolerance_used) article.append(el("p", gpsQuality(row.best), "small muted"));
      article.append(details(row)); card.append(article);
    }); nodes.push(card);
  });
  if (!nodes.length) nodes.push(el("p", snapshot.coverage ? "Nessuna salita Climbfinder riconosciuta per questi filtri." : "Premi Aggiorna salite per confrontare lo storico bici Garmin con il catalogo.", "card"));
  $("climb-groups").replaceChildren(...nodes);
}
async function load() {
  const next = await api("/api/climbs"), changed = !snapshot || snapshot.generated_at !== next.generated_at;
  snapshot = next; const c = snapshot.coverage, cat = snapshot.catalog;
  $("count-climbs").textContent = c?.detected_climbs ?? "—"; $("count-rides").textContent = c?.cycling_activities ?? "—";
  $("count-repeats").textContent = snapshot.rows.filter(r => r.attempt_count > 1).length;
  $("count-places").textContent = `${new Set(snapshot.rows.map(r => r.country)).size} / ${new Set(snapshot.rows.map(r => r.country + r.region)).size}`;
  $("history-start").textContent = c ? `Dal ${date(c.oldest_date)}` : "Storico Garmin"; $("updated").textContent = `Aggiornato: ${date(snapshot.generated_at)}`;
  $("coverage").textContent = c ? `${c.attempts} passaggi riconosciuti · ${c.matched_rides} uscite con salite riconosciute · ${c.rides_without_catalog_match} uscite senza corrispondenze.${c.details_missing ? ` ${c.details_missing} uscite senza GPS/altimetria utilizzabili.` : ""}` : "";
  $("method-note").textContent = snapshot.note;
  $("catalog-coverage").textContent = cat ? `Catalogo locale: ${cat.routes.toLocaleString("it-IT")} percorsi${cat.regions.length ? ` di ${cat.regions.join(" e ")}` : " nelle aree importate"} · importato il ${date(cat.imported_at)}. ${cat.import ? "Geometrie della mappa Climbfinder: possono essere semplificate. " : ""}Altre regioni richiedono l’estensione del catalogo.` : "Catalogo locale non ancora analizzato.";
  if (changed) {filters(); renderGroups();}
  if (snapshot.progress) notice(`Analisi in corso · ${snapshot.progress.current}/${snapshot.progress.total} uscite.`); else if (snapshot.error) notice(snapshot.error, true);
}
$("country-filter").onchange = () => {filters(); renderGroups();}; $("region-filter").onchange = () => {filters(); renderGroups();};
$("zone-filter").onchange = renderGroups; $("search").oninput = renderGroups; $("fit-map").onclick = fitMap;
$("fullscreen-map").onclick = toggleMapFullscreen;
$("refresh-climbs").onclick = async () => {
  if (busy) return; busy = true; $("refresh-climbs").disabled = true; notice("Confronto delle uscite Garmin con i percorsi Climbfinder…");
  try {const data = await api("/api/climbs/refresh", "POST"); await load(); notice(`${data.coverage.detected_climbs} salite nominate · ${data.coverage.attempts} passaggi riconosciuti.`);} catch (error) {notice(error.message, true);} finally {busy = false; $("refresh-climbs").disabled = false;}
};
load().catch(e => notice(e.message, true)); setInterval(() => {if (!busy) load().catch(e => notice(e.message, true));}, 15000);

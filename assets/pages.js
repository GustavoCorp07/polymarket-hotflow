const $ = (id) => document.getElementById(id);
const NOTICE = "Static GitHub Pages demo — for live local ledger use `hotflow dashboard`";
const bundle = window.HOTFLOW_PAGES_DEMO || {};
const rotateFiles = Array.isArray(bundle.rotate) && bundle.rotate.length
  ? bundle.rotate
  : ["state.json", "demo-state.json"];
const intervalMs = Number(bundle.interval_ms) || 2000;
let frames = Array.isArray(bundle.frames) ? bundle.frames.slice() : [];
let idx = 0;

function fmt(n, digits) {
  if (n === null || n === undefined || n === "") return "—";
  const x = Number(n);
  if (!Number.isFinite(x)) return "—";
  return x.toFixed(digits);
}
function pct(n) {
  if (n === null || n === undefined || n === "") return "—";
  const x = Number(n);
  if (!Number.isFinite(x)) return "—";
  return (x * 100).toFixed(2) + "%";
}
function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
  }[c]));
}
function pill(text, cls) {
  return `<span class="pill ${cls}">${esc(text)}</span>`;
}
function render(data) {
  const h = data.health || {};
  const ks = data.kill_switch || {};
  const gates = data.live_gates || {};
  const led = data.ledger || {};
  const mode = data.mode || h.mode || "paper";
  const frame = data.demo_index || ((idx % Math.max(rotateFiles.length, 1)) + 1);
  const total = data.demo_count || rotateFiles.length || frames.length || 1;
  $("status-pills").innerHTML = [
    pill("STATIC DEMO", "demo"),
    pill("mode " + mode, mode === "paper" ? "on" : "off"),
    pill(ks.tripped ? ("kill " + (ks.reason || "TRIPPED")) : "kill closed", ks.tripped ? "off" : "on"),
    pill(gates.closed ? "live gates CLOSED" : "live gates OPEN", gates.closed ? "on" : "off"),
    pill(h.ready ? "ready" : "not ready", h.ready ? "on" : "warn"),
    pill("cycles " + (data.cycle_count || 0), "warn"),
    pill("demo frame " + frame + "/" + total, "demo"),
  ].join("");
  $("kpis").innerHTML = [
    ["Equity", fmt(led.equity, 2), "paper ledger"],
    ["Realized PnL", fmt(led.realized_pnl, 4), "closed fills"],
    ["Unrealized PnL", fmt(led.unrealized_pnl, 4), "last marks"],
    ["Drawdown", pct(led.drawdown), "from peak equity"],
    ["Open positions", String(data.open_positions ?? led.open_positions ?? 0), "tokens with qty"],
    ["Win rate", pct(led.win_rate), (led.closed_count || 0) + " closed"],
  ].map(([k, v, hint]) =>
    `<article class="card"><div class="label">${esc(k)}</div><div class="value">${esc(v)}</div><div class="hint">${esc(hint)}</div></article>`
  ).join("");
  const feeds = data.feeds || {};
  const keys = Object.keys(feeds);
  $("feeds").innerHTML = keys.length
    ? keys.map((name) => {
        const v = feeds[name];
        const ok = Number(v) >= 1;
        return pill(name + (v === null || v === undefined ? " n/a" : (ok ? " fresh" : " stale")), ok ? "on" : "off");
      }).join("")
    : `<div class="empty">No feed gauges yet (idle or --mock without live sockets).</div>`;
  const hot = data.hot_markets || [];
  $("hot").innerHTML = hot.length ? `<table><thead><tr>
    <th>Market</th><th>Tier</th><th>HMS</th><th>Decision</th><th>Reason</th><th>Spread</th>
  </tr></thead><tbody>${hot.map((row) => `<tr>
    <td class="mono">${esc(row.market_id)}</td>
    <td>${esc(row.tier || "—")}</td>
    <td>${esc(fmt(row.hms, 1))}</td>
    <td class="${esc((row.decision || "").toLowerCase())}">${esc(row.decision)}</td>
    <td class="mono">${esc(row.reason || "")}</td>
    <td>${esc(row.spread_regime || "—")}</td>
  </tr>`).join("")}</tbody></table>` : `<div class="empty">No cycle in this snapshot.</div>`;
  const recent = data.recent || [];
  $("recent").innerHTML = recent.length ? `<table><thead><tr>
    <th>When</th><th>Decision</th><th>Market</th><th>Primary</th><th>reason_codes</th><th>spread_regime</th>
  </tr></thead><tbody>${recent.map((row) => `<tr>
    <td class="mono">${esc((row.ts || "").replace("T", " ").slice(0, 19))}</td>
    <td class="${esc((row.decision || "").toLowerCase())}">${esc(row.decision)}</td>
    <td class="mono">${esc(row.market_id)}</td>
    <td>${esc(row.reason)}</td>
    <td class="mono">${esc((row.reason_codes || []).join(", "))}</td>
    <td>${esc(row.spread_regime || "—")}</td>
  </tr>`).join("")}</tbody></table>` : `<div class="empty">No TRADE/SKIP rows yet.</div>`;
  $("meta").textContent = " " + NOTICE + " gen=" + (data.generation || 0)
    + " updated=" + (data.updated_at || "")
    + " source=" + (data.demo_source || "paper-run --mock");
}

async function fetchJson(path) {
  const r = await fetch(path + (path.includes("?") ? "&" : "?") + "t=" + Date.now(), { cache: "no-store" });
  if (!r.ok) throw new Error(String(r.status));
  return r.json();
}

async function tick() {
  const n = rotateFiles.length;
  const file = rotateFiles[idx % n];
  let data = null;
  try {
    data = await fetchJson(file);
    frames[idx % n] = data;
  } catch (err) {
    data = frames[idx % Math.max(frames.length, 1)] || frames[0] || null;
  }
  if (!data) {
    try {
      data = await fetchJson("state.json");
    } catch (err) {
      try {
        data = await fetchJson("demo-state.json");
      } catch (inner) {
        return;
      }
    }
  }
  data.static_pages_demo = true;
  if (!data.demo_notice) data.demo_notice = NOTICE;
  render(data);
  idx += 1;
}

if (frames[0]) render(frames[0]);
tick();
setInterval(tick, intervalMs);

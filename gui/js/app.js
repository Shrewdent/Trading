/* App shell: tabs, toasts, and the three tab controllers. */

let API = null;
let STRATEGIES = [];
let PAPER_POLL_TIMER = null;

// ---------- Bootstrapping ----------

window.addEventListener("pywebviewready", init);
// Fallback for dev-in-browser / slow bridge init.
if (window.pywebview && window.pywebview.api) init();

async function init() {
  if (API) return;
  API = window.pywebview.api;

  wireSidebar();
  wireTabs();
  wireBacktesterTab();
  wireResultsTab();
  wirePaperTraderTab();

  await loadStrategies();
  setDefaultBacktestDates();
  await loadConfigIntoForm();

  showTab("backtester");
}

// ---------- Toasts ----------

function toast(message, type = "info") {
  const container = document.getElementById("toast-container");
  const el = document.createElement("div");
  el.className = `toast ${type}`;
  el.textContent = message;
  container.appendChild(el);
  setTimeout(() => el.remove(), 5000);
}

// ---------- Sidebar / Tabs ----------

function wireSidebar() {
  document.getElementById("sidebar-toggle").addEventListener("click", () => {
    document.getElementById("sidebar").classList.toggle("collapsed");
  });
}

function wireTabs() {
  document.querySelectorAll(".tab-btn").forEach((btn) => {
    btn.addEventListener("click", () => showTab(btn.dataset.tab));
  });
}

const TAB_TITLES = {
  backtester: "Backtester",
  "paper-trader": "Paper Trader",
  results: "Results History",
};

const FIXED_CHART_IDS = [
  "price-chart",
  "indicator-chart",
  "equity-chart",
  "results-price-chart",
  "results-indicator-chart",
  "results-equity-chart",
];

function resizeAllCharts() {
  FIXED_CHART_IDS.forEach(Charts.resizeChart);
  document.querySelectorAll(".session-chart").forEach((el) => Charts.resizeChart(el.id));
}

function showTab(name) {
  document.querySelectorAll(".tab-btn").forEach((b) => b.classList.toggle("active", b.dataset.tab === name));
  document.querySelectorAll(".tab-panel").forEach((p) => p.classList.remove("active"));
  document.getElementById(`tab-${name}`).classList.add("active");
  document.getElementById("header-tab-name").textContent = TAB_TITLES[name];

  if (name === "results") loadHistory();
  if (name === "paper-trader") onPaperTraderTabShown();

  // Charts need a real size to lay out against; nudge them after the panel is visible.
  requestAnimationFrame(resizeAllCharts);
}

window.addEventListener("resize", resizeAllCharts);

// ---------- Shared helpers ----------

async function loadStrategies() {
  const res = await API.get_strategies();
  if (!res.ok) {
    toast(res.error, "error");
    return;
  }
  STRATEGIES = res.data;
  ["bt-strategy", "pt-strategy"].forEach((id) => {
    const sel = document.getElementById(id);
    sel.innerHTML = STRATEGIES.map((s) => `<option value="${s.name}">${s.label}</option>`).join("");
  });
}

function setDefaultBacktestDates() {
  const end = new Date();
  const start = new Date();
  start.setFullYear(start.getFullYear() - 5);
  document.getElementById("bt-end").value = end.toISOString().slice(0, 10);
  document.getElementById("bt-start").value = start.toISOString().slice(0, 10);
  document.getElementById("bt-ticker").value = "SPY";
}

async function loadConfigIntoForm() {
  const res = await API.get_config();
  if (!res.ok) return;
  const cfg = res.data;
  if (cfg.last_used) {
    if (cfg.last_used.ticker) document.getElementById("bt-ticker").value = cfg.last_used.ticker;
    if (cfg.last_used.strategy) document.getElementById("bt-strategy").value = cfg.last_used.strategy;
    if (cfg.last_used.start_date) document.getElementById("bt-start").value = cfg.last_used.start_date;
    if (cfg.last_used.end_date) document.getElementById("bt-end").value = cfg.last_used.end_date;
  }
}

function setStatus(elId, message, kind) {
  const el = document.getElementById(elId);
  el.className = "status-line" + (kind ? ` ${kind}` : "");
  el.innerHTML = message;
}

function fmtPct(v) {
  if (v === null || v === undefined || Number.isNaN(v)) return "--";
  const sign = v > 0 ? "+" : "";
  return `${sign}${v.toFixed(2)}%`;
}

function pctClass(v) {
  if (v === null || v === undefined || Number.isNaN(v)) return "";
  return v > 0 ? "positive" : v < 0 ? "negative" : "";
}

// =====================================================================
// Backtester
// =====================================================================

function wireBacktesterTab() {
  document.getElementById("bt-run").addEventListener("click", runBacktest);
}

async function runBacktest() {
  const btn = document.getElementById("bt-run");
  const ticker = document.getElementById("bt-ticker").value.trim();
  const startDate = document.getElementById("bt-start").value;
  const endDate = document.getElementById("bt-end").value;
  const strategyName = document.getElementById("bt-strategy").value;
  const trainTestSplit = document.getElementById("bt-split").checked;

  if (!ticker || !startDate || !endDate) {
    setStatus("bt-status", "Ticker and both dates are required.", "error");
    return;
  }

  btn.disabled = true;
  document.getElementById("bt-results").classList.add("hidden");
  setStatus("bt-status", '<span class="spinner"></span> Downloading data and running backtest...', "");

  const res = await API.run_backtest({
    ticker,
    start_date: startDate,
    end_date: endDate,
    strategy: strategyName,
    train_test_split: trainTestSplit,
  });

  btn.disabled = false;

  if (!res.ok) {
    setStatus("bt-status", res.error, "error");
    return;
  }

  setStatus("bt-status", `Done — ${res.data.chart_data.ohlc.length} trading days loaded.`, "success");
  document.getElementById("bt-results").classList.remove("hidden");
  renderBacktestResult(res.data, {
    metricsPrefix: "m-",
    pricePanel: "price-chart",
    indicatorPanel: "indicator-chart",
    equityPanel: "equity-chart",
    splitPanelId: "split-panel",
    splitTrainId: "split-train",
    splitTestId: "split-test",
  });
}

function renderBacktestResult(result, ids) {
  const set = (suffix, value, cls) => {
    const el = document.getElementById(`${ids.metricsPrefix}${suffix}`);
    if (!el) return;
    el.textContent = value;
    el.className = "metric-value" + (cls ? ` ${cls}` : "");
  };

  set("return", fmtPct(result.return_pct), pctClass(result.return_pct));
  set("benchmark", fmtPct(result.benchmark_return_pct), pctClass(result.benchmark_return_pct));
  const vsBenchmark = result.return_pct - result.benchmark_return_pct;
  set("vs-benchmark", fmtPct(vsBenchmark), pctClass(vsBenchmark));
  set("winrate", `${result.win_rate.toFixed(1)}%`);
  set("maxdd", fmtPct(result.max_dd), "negative");
  set("sharpe", result.sharpe.toFixed(2));
  set("trades", result.num_trades);
  set("duration", result.avg_trade_duration ? `${result.avg_trade_duration.toFixed(1)}d` : "--");

  if (ids.splitPanelId) {
    const splitPanel = document.getElementById(ids.splitPanelId);
    const split = result.chart_data.split;
    if (split) {
      splitPanel.classList.remove("hidden");
      renderSplitTable(ids.splitTrainId, split.train);
      renderSplitTable(ids.splitTestId, split.test);
    } else {
      splitPanel.classList.add("hidden");
    }
  }

  Charts.renderBacktestCharts(ids.pricePanel, ids.indicatorPanel, ids.equityPanel, result.chart_data);
}

function renderSplitTable(elId, seg) {
  const table = document.getElementById(elId);
  const rows = [
    ["Range", `${seg.start_date} → ${seg.end_date}`],
    ["Return", fmtPct(seg.return_pct)],
    ["Buy & Hold", fmtPct(seg.benchmark_return_pct)],
    ["Win Rate", `${seg.win_rate.toFixed(1)}%`],
    ["Max Drawdown", fmtPct(seg.max_dd)],
    ["Sharpe", seg.sharpe.toFixed(2)],
    ["# Trades", seg.num_trades],
  ];
  table.innerHTML = rows.map(([label, val]) => `<tr><td>${label}</td><td>${val}</td></tr>`).join("");
}

// =====================================================================
// Results History
// =====================================================================

let HISTORY_ROWS = [];
let HISTORY_SORT = { key: "created_at", dir: -1 };

function wireResultsTab() {
  document.getElementById("results-filter").addEventListener("input", renderHistoryTable);
  document.querySelectorAll("#results-table th[data-sort]").forEach((th) => {
    th.addEventListener("click", () => {
      const key = th.dataset.sort;
      HISTORY_SORT.dir = HISTORY_SORT.key === key ? -HISTORY_SORT.dir : -1;
      HISTORY_SORT.key = key;
      renderHistoryTable();
    });
  });
}

async function loadHistory() {
  const res = await API.get_history();
  if (!res.ok) {
    toast(res.error, "error");
    return;
  }
  HISTORY_ROWS = res.data;
  renderHistoryTable();
}

function renderHistoryTable() {
  const filter = document.getElementById("results-filter").value.trim().toLowerCase();
  let rows = HISTORY_ROWS.filter(
    (r) => !filter || r.ticker.toLowerCase().includes(filter) || r.strategy.toLowerCase().includes(filter)
  );

  rows = rows.slice().sort((a, b) => {
    const av = a[HISTORY_SORT.key];
    const bv = b[HISTORY_SORT.key];
    if (av < bv) return -1 * HISTORY_SORT.dir;
    if (av > bv) return 1 * HISTORY_SORT.dir;
    return 0;
  });

  const strategyLabel = (name) => (STRATEGIES.find((s) => s.name === name) || {}).label || name;

  const tbody = document.querySelector("#results-table tbody");
  tbody.innerHTML = rows
    .map(
      (r) => `
      <tr data-id="${r.id}">
        <td>${r.created_at.replace("T", " ")}</td>
        <td><span class="badge">${r.ticker}</span></td>
        <td>${strategyLabel(r.strategy)}</td>
        <td>${r.start_date} → ${r.end_date}</td>
        <td class="${pctClass(r.return_pct)}">${fmtPct(r.return_pct)}</td>
        <td class="${pctClass(r.benchmark_return_pct)}">${fmtPct(r.benchmark_return_pct)}</td>
        <td>${r.win_rate.toFixed(1)}%</td>
        <td class="cell-negative">${fmtPct(r.max_dd)}</td>
        <td>${r.sharpe.toFixed(2)}</td>
        <td><button class="row-delete-btn" data-id="${r.id}" title="Delete">&#10005;</button></td>
      </tr>`
    )
    .join("");

  tbody.querySelectorAll("tr").forEach((tr) => {
    tr.addEventListener("click", (e) => {
      if (e.target.closest(".row-delete-btn")) return;
      showBacktestDetail(Number(tr.dataset.id));
    });
  });
  tbody.querySelectorAll(".row-delete-btn").forEach((btn) => {
    btn.addEventListener("click", async (e) => {
      e.stopPropagation();
      const id = Number(btn.dataset.id);
      const res = await API.delete_backtest(id);
      if (!res.ok) {
        toast(res.error, "error");
        return;
      }
      HISTORY_ROWS = HISTORY_ROWS.filter((r) => r.id !== id);
      renderHistoryTable();
      document.getElementById("results-detail").classList.add("hidden");
    });
  });
}

async function showBacktestDetail(id) {
  const res = await API.get_backtest_detail(id);
  if (!res.ok) {
    toast(res.error, "error");
    return;
  }
  const record = res.data;
  const detail = document.getElementById("results-detail");
  detail.classList.remove("hidden");

  const metricsPanel = document.getElementById("results-detail-metrics");
  const vsBenchmark = record.return_pct - record.benchmark_return_pct;
  const cards = [
    ["Ticker / Strategy", `${record.ticker} — ${(STRATEGIES.find((s) => s.name === record.strategy) || {}).label || record.strategy}`],
    ["Total Return", fmtPct(record.return_pct), pctClass(record.return_pct)],
    ["vs Buy & Hold", fmtPct(vsBenchmark), pctClass(vsBenchmark)],
    ["Win Rate", `${record.win_rate.toFixed(1)}%`],
    ["Max Drawdown", fmtPct(record.max_dd), "negative"],
    ["Sharpe", record.sharpe.toFixed(2)],
    ["# Trades", record.num_trades],
  ];
  metricsPanel.innerHTML = cards
    .map(
      ([label, val, cls]) =>
        `<div class="metric-card"><div class="metric-label">${label}</div><div class="metric-value${cls ? " " + cls : ""}">${val}</div></div>`
    )
    .join("");

  const splitPanel = document.getElementById("results-split-panel");
  const split = record.chart_data.split;
  if (split) {
    splitPanel.classList.remove("hidden");
    renderSplitTable("results-split-train", split.train);
    renderSplitTable("results-split-test", split.test);
  } else {
    splitPanel.classList.add("hidden");
  }

  Charts.renderPriceChart("results-price-chart", record.chart_data);
  Charts.renderIndicatorChart("results-indicator-chart", record.chart_data);
  Charts.renderEquityChart("results-equity-chart", record.chart_data);

  detail.scrollIntoView({ behavior: "smooth", block: "start" });
}

// =====================================================================
// Paper Trader
// =====================================================================

let ALL_PAPER_TRADES = [];
let PAPER_HISTORY_SORT = { key: "timestamp", dir: -1 };

function wirePaperTraderTab() {
  document.getElementById("pt-save-keys").addEventListener("click", savePaperKeys);
  document.getElementById("pt-start").addEventListener("click", startPaperTrader);
  document.getElementById("pt-history-filter").addEventListener("input", renderAllPaperTradesTable);
  document.querySelectorAll("#pt-all-history th[data-sort]").forEach((th) => {
    th.addEventListener("click", () => {
      const key = th.dataset.sort;
      PAPER_HISTORY_SORT.dir = PAPER_HISTORY_SORT.key === key ? -PAPER_HISTORY_SORT.dir : -1;
      PAPER_HISTORY_SORT.key = key;
      renderAllPaperTradesTable();
    });
  });
}

async function onPaperTraderTabShown() {
  const res = await API.get_config();
  const hasKeys = res.ok && res.data.has_alpaca_keys;

  document.getElementById("pt-no-keys").classList.toggle("hidden", hasKeys);
  document.getElementById("pt-dashboard").classList.toggle("hidden", !hasKeys);

  if (hasKeys) {
    startPaperPolling();
  } else {
    stopPaperPolling();
  }
}

function renderAllPaperTradesTable() {
  const filter = document.getElementById("pt-history-filter").value.trim().toLowerCase();
  let rows = ALL_PAPER_TRADES.filter((t) => !filter || t.ticker.toLowerCase().includes(filter));

  rows = rows.slice().sort((a, b) => {
    const av = a[PAPER_HISTORY_SORT.key];
    const bv = b[PAPER_HISTORY_SORT.key];
    if (av < bv) return -1 * PAPER_HISTORY_SORT.dir;
    if (av > bv) return 1 * PAPER_HISTORY_SORT.dir;
    return 0;
  });

  const tbody = document.querySelector("#pt-all-history tbody");
  tbody.innerHTML = rows
    .map(
      (t) => `
      <tr>
        <td>${t.timestamp}</td>
        <td><span class="badge">${t.ticker}</span></td>
        <td>${t.signal}</td>
        <td class="${t.side === "buy" ? "cell-positive" : "cell-negative"}">${t.side}</td>
        <td>${t.qty ?? "--"}</td>
        <td>${t.price !== null && t.price !== undefined ? `$${Number(t.price).toFixed(2)}` : "--"}</td>
        <td>${t.status}</td>
      </tr>`
    )
    .join("");
}

async function savePaperKeys() {
  const apiKey = document.getElementById("pt-api-key").value.trim();
  const secretKey = document.getElementById("pt-secret-key").value.trim();
  if (!apiKey || !secretKey) {
    toast("Both API key and secret key are required.", "error");
    return;
  }
  const res = await API.save_alpaca_keys(apiKey, secretKey);
  if (!res.ok) {
    toast(res.error, "error");
    return;
  }
  toast("Alpaca keys saved.", "success");
  onPaperTraderTabShown();
}

async function startPaperTrader() {
  const ticker = document.getElementById("pt-ticker").value.trim().toUpperCase();
  const strategyName = document.getElementById("pt-strategy").value;
  const allocation = parseFloat(document.getElementById("pt-allocation").value);

  if (!ticker) {
    toast("Enter a ticker to trade.", "error");
    return;
  }
  if (!allocation || allocation <= 0) {
    toast("Enter a dollar amount to allocate to this session.", "error");
    return;
  }

  const res = await API.start_paper_trader({ ticker, strategy: strategyName, allocated_dollars: allocation });
  if (!res.ok) {
    toast(res.error, "error");
    return;
  }
  toast(`Paper trading started on ${ticker} with $${allocation.toFixed(0)} allocated.`, "success");
  document.getElementById("pt-ticker").value = "";
  document.getElementById("pt-allocation").value = "";
  refreshPaperStatus();
}

async function stopPaperTrader(ticker) {
  const res = await API.stop_paper_trader(ticker);
  if (!res.ok) {
    toast(res.error, "error");
    return;
  }
  toast(`Paper trading stopped for ${ticker}.`, "info");
  refreshPaperStatus();
}

async function closePaperPosition(ticker) {
  const res = await API.close_position(ticker);
  if (!res.ok) {
    toast(res.error, "error");
    return;
  }
  if (res.data.market_open === false) {
    toast(`Close order submitted for ${ticker}, but the market is closed -- it will sit unfilled until market open.`, "info");
  } else {
    toast(`Position closed for ${ticker}.`, "success");
  }
  refreshPaperStatus();
}

function startPaperPolling() {
  if (PAPER_POLL_TIMER) return;
  refreshPaperStatus();
  PAPER_POLL_TIMER = setInterval(refreshPaperStatus, 5000);
}

function stopPaperPolling() {
  if (PAPER_POLL_TIMER) {
    clearInterval(PAPER_POLL_TIMER);
    PAPER_POLL_TIMER = null;
  }
}

async function refreshPaperStatus() {
  const res = await API.get_paper_status();
  if (!res.ok) return;
  const { account, sessions, open_positions, realized_pnl, all_trades } = res.data;

  document.getElementById("header-equity").textContent = account.equity ? `$${account.equity.toFixed(2)}` : "--";
  document.getElementById("header-bp").textContent = account.buying_power ? `$${account.buying_power.toFixed(2)}` : "--";
  document.getElementById("paper-account-summary").classList.remove("hidden");

  sessions.forEach((s) => (s.notifications || []).forEach((n) => toast(n.message, n.level || "info")));

  const runningSessions = sessions.filter((s) => s.running);

  const liveBadge = document.getElementById("paper-live-badge");
  liveBadge.textContent = `Live: ${runningSessions.length > 0 ? "Yes" : "No"}`;
  liveBadge.classList.toggle("on", runningSessions.length > 0);

  if (runningSessions.length === 0) {
    setStatus("pt-status", "No sessions running.", "");
  } else {
    const anyOpen = runningSessions.some((s) => s.market_open);
    const plural = runningSessions.length > 1 ? "s" : "";
    setStatus(
      "pt-status",
      `${anyOpen ? "Market open" : "Market closed"} &middot; ${runningSessions.length} session${plural} running`,
      "success"
    );
  }

  const container = document.getElementById("pt-sessions");
  const activeTickers = new Set(runningSessions.map((s) => s.ticker));
  container.querySelectorAll(".session-card").forEach((card) => {
    if (!activeTickers.has(card.dataset.ticker)) card.remove();
  });

  runningSessions.forEach((s) => updateSessionCard(getOrCreateSessionCard(s.ticker), s));

  renderOpenPositions(open_positions || []);
  renderRealizedPnl(realized_pnl || { total_pnl_dollars: 0, num_closed_trades: 0, win_rate: 0 });

  ALL_PAPER_TRADES = all_trades || [];
  renderAllPaperTradesTable();

  resizeAllCharts();
}

function renderOpenPositions(positions) {
  const tbody = document.querySelector("#pt-open-positions tbody");
  const emptyHint = document.getElementById("pt-open-positions-empty");

  emptyHint.classList.toggle("hidden", positions.length > 0);

  tbody.innerHTML = positions
    .map(
      (p) => `
      <tr>
        <td><span class="badge">${p.symbol}</span></td>
        <td>${p.qty}</td>
        <td>$${p.entry_price.toFixed(2)}</td>
        <td>$${p.market_value.toFixed(2)}</td>
        <td class="${pctClass(p.unrealized_pl_pct)}">${fmtPct(p.unrealized_pl_pct)}</td>
        <td><span class="badge${p.session_active ? " badge-live on" : ""}">${p.session_active ? "Yes" : "No"}</span></td>
        <td><button class="btn btn-secondary position-close-btn" data-ticker="${p.symbol}">Close</button></td>
      </tr>`
    )
    .join("");

  tbody.querySelectorAll(".position-close-btn").forEach((btn) => {
    btn.addEventListener("click", () => closePaperPosition(btn.dataset.ticker));
  });
}

function renderRealizedPnl(pnl) {
  const totalEl = document.getElementById("pt-realized-total");
  totalEl.textContent = `${pnl.total_pnl_dollars >= 0 ? "+" : ""}$${pnl.total_pnl_dollars.toFixed(2)}`;
  totalEl.className = "metric-value " + pctClass(pnl.total_pnl_dollars);
  document.getElementById("pt-realized-count").textContent = pnl.num_closed_trades;
  document.getElementById("pt-realized-winrate").textContent = `${pnl.win_rate.toFixed(1)}%`;

  const warningEl = document.getElementById("pt-realized-pnl-warning");
  const unmatched = pnl.unmatched_buys || 0;
  if (unmatched > 0) {
    const plural = unmatched > 1 ? "s" : "";
    warningEl.textContent = `${unmatched} unmatched buy${plural} found in the trade log -- P&L pairing may be inaccurate for those trades.`;
    warningEl.classList.remove("hidden");
  } else {
    warningEl.classList.add("hidden");
  }
}

function getOrCreateSessionCard(ticker) {
  const existing = document.querySelector(`#pt-sessions .session-card[data-ticker="${ticker}"]`);
  if (existing) return existing;

  const template = document.getElementById("pt-session-card-template");
  const fragment = template.content.cloneNode(true);
  const card = fragment.querySelector(".session-card");
  card.dataset.ticker = ticker;
  card.querySelector(".session-ticker").textContent = ticker;
  card.querySelector(".session-chart").id = `pt-chart-${ticker}`;
  card.querySelector(".session-stop").addEventListener("click", () => stopPaperTrader(ticker));
  card.querySelector(".session-close-position").addEventListener("click", () => closePaperPosition(ticker));

  document.getElementById("pt-sessions").appendChild(card);
  return card;
}

function updateSessionCard(card, s) {
  card.querySelector(".session-strategy").textContent = (STRATEGIES.find((x) => x.name === s.strategy) || {}).label || s.strategy;
  card.querySelector(".session-allocation").textContent = `$${Number(s.allocated_dollars).toFixed(0)} alloc`;
  card.querySelector(".session-close-position").classList.toggle("hidden", !s.position || s.position === "flat");

  const statusParts = [
    s.market_open ? "Market open" : "Market closed",
    s.last_update ? `Last update: ${s.last_update}` : null,
  ].filter(Boolean);
  const statusEl = card.querySelector(".session-status");
  statusEl.className = "session-status status-line success";
  statusEl.innerHTML = statusParts.join(" &middot; ");

  card.querySelector(".session-position").textContent = s.position === "long" ? "Long" : "Flat";
  card.querySelector(".session-entry").textContent = s.entry_price ? `$${s.entry_price.toFixed(2)}` : "--";
  const uplEl = card.querySelector(".session-upl");
  uplEl.textContent = s.unrealized_pl !== null && s.unrealized_pl !== undefined ? fmtPct(s.unrealized_pl) : "--";
  uplEl.className = "metric-value session-upl " + pctClass(s.unrealized_pl);

  if (s.chart_data) {
    Charts.renderPriceChart(card.querySelector(".session-chart").id, s.chart_data);
  }

  renderSessionTradeHistory(card, s.trade_history || []);
}

function renderSessionTradeHistory(card, trades) {
  const tbody = card.querySelector(".session-trade-history tbody");
  tbody.innerHTML = trades
    .slice()
    .reverse()
    .map(
      (t) => `
      <tr>
        <td>${t.timestamp}</td>
        <td>${t.signal}</td>
        <td class="${t.side === "buy" ? "cell-positive" : "cell-negative"}">${t.side}</td>
        <td>${t.qty}</td>
        <td>$${Number(t.price).toFixed(2)}</td>
        <td>${t.status}</td>
      </tr>`
    )
    .join("");
}

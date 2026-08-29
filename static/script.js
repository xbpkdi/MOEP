const socket = io();

const lastPriceEl = document.getElementById("last-price");
const changeBadgeEl = document.getElementById("change-badge");
const headerSpreadEl = document.getElementById("header-spread");
const headerSeqEl = document.getElementById("header-seq");
const headerTimeEl = document.getElementById("header-time");
const connBoxEl = document.getElementById("conn-box");
const connDotEl = document.getElementById("conn-dot");
const connLabelEl = document.getElementById("conn-label");
const orderBookBodyEl = document.getElementById("order-book-body");
const tradesBodyEl = document.getElementById("trades-body");
const logListEl = document.getElementById("log-list");
const gapBannerEl = document.getElementById("gap-banner");
const priceInput = document.getElementById("price-input");
const qtyInput = document.getElementById("qty-input");
const orderHintEl = document.getElementById("order-hint");
const submitBtn = document.getElementById("submit-order");
const clearBtn = document.getElementById("clear-form");
const sideToggleEl = document.getElementById("side-toggle");

let selectedSide = "BUY";
let sessionOpenPrice = null;
let lastTradePrice = null;
let currentSpread = null;
let gapHideTimer = null;
const recentTrades = [];
const MAX_LOG_ROWS = 80;
const EMPTY_LEVEL = { price: null, qty: null };

function padTime(value) {
  return String(value).padStart(2, "0");
}

function formatClock(ts) {
  const date = ts ? new Date(ts * 1000) : new Date();
  const ms = String(date.getMilliseconds()).padStart(3, "0");
  return `${padTime(date.getHours())}:${padTime(date.getMinutes())}:${padTime(date.getSeconds())}.${ms}`;
}

function formatPrice(value) {
  if (value === null || value === undefined || value === "") {
    return "—";
  }
  return Number(value).toFixed(2);
}

function formatQty(value) {
  if (value === null || value === undefined || value === "") {
    return "—";
  }
  return String(value);
}

function setConnectionStatus(connected) {
  connBoxEl.classList.toggle("connected", connected);
  connBoxEl.classList.toggle("disconnected", !connected);
  connDotEl.className = connected ? "dot green" : "dot pink";
  connLabelEl.textContent = connected ? "CONNECTED" : "DISCONNECTED";
}

function updateChangeBadge(price) {
  if (sessionOpenPrice === null) {
    sessionOpenPrice = price;
  }
  const delta = price - sessionOpenPrice;
  const pct = sessionOpenPrice === 0 ? 0 : (delta / sessionOpenPrice) * 100;
  const sign = delta >= 0 ? "+" : "";
  const arrow = delta >= 0 ? "▲" : "▼";
  changeBadgeEl.textContent = `${sign}${delta.toFixed(2)}  ${sign}${pct.toFixed(2)}%  ${arrow}`;
  changeBadgeEl.classList.toggle("up", delta > 0);
  changeBadgeEl.classList.toggle("down", delta < 0);
}

function updateTickerPrice(price, seq, ts) {
  if (price === null || price === undefined) {
    return;
  }
  lastTradePrice = Number(price);
  lastPriceEl.textContent = formatPrice(lastTradePrice);
  updateChangeBadge(lastTradePrice);
  if (seq !== undefined && seq !== null) {
    headerSeqEl.textContent = seq;
  }
  headerTimeEl.textContent = formatClock(ts);
}

function padLevels(levels) {
  const rows = (levels || []).slice(0, 5);
  while (rows.length < 5) {
    rows.push(EMPTY_LEVEL);
  }
  return rows;
}

function maxQty(bids, asks) {
  let maxValue = 1;
  bids.concat(asks).forEach((level) => {
    if (level && level.qty) {
      maxValue = Math.max(maxValue, level.qty);
    }
  });
  return maxValue;
}

function updateOrderBookDisplay(payload) {
  const bids = padLevels(payload.bids);
  const asks = padLevels(payload.asks);
  const depthMax = maxQty(bids, asks);
  const bid = payload.best_bid;
  const ask = payload.best_ask;
  if (bid !== null && ask !== null && bid !== undefined && ask !== undefined) {
    currentSpread = Number(ask) - Number(bid);
    headerSpreadEl.textContent = currentSpread.toFixed(2);
  } else {
    currentSpread = null;
    headerSpreadEl.textContent = "—";
  }

  if (lastTradePrice === null && bid !== null && ask !== null && bid !== undefined && ask !== undefined) {
    updateTickerPrice((Number(bid) + Number(ask)) / 2, payload.seq, payload.ts);
  } else if (payload.seq !== undefined) {
    headerSeqEl.textContent = payload.seq;
    headerTimeEl.textContent = formatClock(payload.ts);
  }

  orderBookBodyEl.innerHTML = "";
  for (let i = 0; i < 5; i += 1) {
    const bidLevel = bids[i] || EMPTY_LEVEL;
    const askLevel = asks[i] || EMPTY_LEVEL;
    const bidWidth = bidLevel.qty ? Math.max(8, (bidLevel.qty / depthMax) * 100) : 0;
    const askWidth = askLevel.qty ? Math.max(8, (askLevel.qty / depthMax) * 100) : 0;
    const midText = currentSpread !== null ? currentSpread.toFixed(2) : "";
    const row = document.createElement("div");
    row.className = "book-row";
    row.innerHTML = `
      <span class="ob-qty">${formatQty(bidLevel.qty)}</span>
      <div class="ob-bid-cell">
        <div class="depth-bar bid-bar" style="width:${bidWidth}%"></div>
        <span class="bid-px">${formatPrice(bidLevel.price)}</span>
      </div>
      <span class="ob-mid">${midText}</span>
      <div class="ob-ask-cell">
        <span class="ask-px">${formatPrice(askLevel.price)}</span>
        <div class="depth-bar ask-bar" style="width:${askWidth}%"></div>
      </div>
      <span class="ob-qty">${formatQty(askLevel.qty)}</span>
    `;
    orderBookBodyEl.appendChild(row);
  }
}

function updateRecentTrades(payload) {
  const side = payload.side === "SELL" ? "SELL" : "BUY";
  recentTrades.unshift({
    time: formatClock(payload.ts),
    price: payload.price,
    qty: payload.qty,
    side,
  });
  if (recentTrades.length > 5) {
    recentTrades.length = 5;
  }
  renderRecentTrades();
  updateTickerPrice(payload.price, payload.seq, payload.ts);
}

function renderRecentTrades() {
  tradesBodyEl.innerHTML = "";
  const rows = recentTrades.slice();
  while (rows.length < 5) {
    rows.push(null);
  }
  rows.forEach((trade) => {
    const row = document.createElement("div");
    if (!trade) {
      row.className = "trade-row";
      row.innerHTML = `<span class="time">—</span><span class="muted">—</span><span class="muted">—</span><span class="muted">—</span>`;
    } else {
      row.className = `trade-row ${trade.side.toLowerCase()}`;
      row.innerHTML = `
        <span class="time">${trade.time}</span>
        <span class="px">${formatPrice(trade.price)}</span>
        <span>${trade.qty}</span>
        <span class="side">${trade.side}</span>
      `;
    }
    tradesBodyEl.appendChild(row);
  });
}

function directionClass(direction) {
  if (direction === "SEND") return "send";
  if (direction === "RECV" || direction === "GAPFL") return "recv";
  if (direction === "WARN") return "warn";
  return "bcast";
}

function appendLogRow(event) {
  const row = document.createElement("div");
  const klass = directionClass(event.direction);
  row.className = `log-row ${klass}`;
  const shownDirection = event.direction === "GAPFL" ? "RECV" : event.direction === "WARN" ? "WARN" : event.direction;
  row.innerHTML = `
    <span class="log-time">${formatClock(event.ts)}</span>
    <span class="log-dir ${klass}">${shownDirection}</span>
    <span class="log-type">${event.msg_type}</span>
    <span class="log-kv">${event.detail || ""}</span>
  `;
  logListEl.prepend(row);
  while (logListEl.children.length > MAX_LOG_ROWS) {
    logListEl.removeChild(logListEl.lastChild);
  }
}

function showGapBanner() {
  gapBannerEl.classList.remove("hidden");
  if (gapHideTimer) {
    clearTimeout(gapHideTimer);
  }
  gapHideTimer = setTimeout(() => {
    gapBannerEl.classList.add("hidden");
  }, 4000);
}

function parsePositiveNumber(raw) {
  const value = Number(raw);
  if (!Number.isFinite(value) || value <= 0) {
    return null;
  }
  return value;
}

function submitNewOrder() {
  const price = parsePositiveNumber(priceInput.value);
  const qty = parsePositiveNumber(qtyInput.value);
  if (price === null || qty === null || !Number.isInteger(qty)) {
    orderHintEl.classList.remove("hidden");
    return;
  }
  orderHintEl.classList.add("hidden");
  socket.emit("submit_order", { side: selectedSide, price, qty: qty });
}

sideToggleEl.addEventListener("click", (event) => {
  const button = event.target.closest(".side-btn");
  if (!button) {
    return;
  }
  selectedSide = button.dataset.side;
  sideToggleEl.querySelectorAll(".side-btn").forEach((el) => {
    el.classList.toggle("active", el === button);
  });
});

document.getElementById("price-up").addEventListener("click", () => {
  const current = Number(priceInput.value) || 0;
  priceInput.value = (current + 0.01).toFixed(2);
});

document.getElementById("price-down").addEventListener("click", () => {
  const current = Number(priceInput.value) || 0;
  priceInput.value = Math.max(0.01, current - 0.01).toFixed(2);
});

document.getElementById("qty-up").addEventListener("click", () => {
  const current = parseInt(qtyInput.value, 10) || 0;
  qtyInput.value = String(current + 1);
});

document.getElementById("qty-down").addEventListener("click", () => {
  const current = parseInt(qtyInput.value, 10) || 0;
  qtyInput.value = String(Math.max(1, current - 1));
});

clearBtn.addEventListener("click", () => {
  priceInput.value = "214.41";
  qtyInput.value = "100";
  orderHintEl.classList.add("hidden");
});

submitBtn.addEventListener("click", submitNewOrder);

socket.on("connect", () => setConnectionStatus(true));
socket.on("disconnect", () => setConnectionStatus(false));
socket.on("log_event", appendLogRow);
socket.on("book_update", updateOrderBookDisplay);
socket.on("trade", updateRecentTrades);
socket.on("gap_alert", showGapBanner);

setConnectionStatus(false);
updateOrderBookDisplay({ bids: [], asks: [] });
renderRecentTrades();

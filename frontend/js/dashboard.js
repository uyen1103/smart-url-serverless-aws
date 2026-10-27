import { getStats, getLinks, ApiError, getApiErrorMessage, isUsingMock } from "./api.js";
import { clear, el, setText } from "./dom.js";
import { renderBars, renderDonut, renderTimeline } from "./charts.js";
import { createPoller } from "./poller.js";
import { mountShell } from "./shell.js";

mountShell();
const rangeSelect = document.querySelector("#range-select");
const linkSelect = document.querySelector("#link-select");
const notice = document.querySelector("#dashboard-notice");
const noticeContent = notice.querySelector(".notice-content");
const anomalyNotice = document.querySelector("#anomaly-notice");
const connectionState = document.querySelector("#connection-state");
const query = new URLSearchParams(window.location.search);
const detailCode = query.get("code") || null;
let poller;
let lastData = null;
let lastUpdatedLabel = "";
let currentRange = "1h";

// Chọn khoảng thời gian và độ chi tiết tương ứng trước khi gọi endpoint thống kê.
function rangeOptions() {
  const to = new Date();
  const from = new Date(to);
  if (currentRange === "15m") from.setMinutes(from.getMinutes() - 15);
  else if (currentRange === "24h") from.setHours(from.getHours() - 24);
  else from.setHours(from.getHours() - 1);
  return {
    from: from.toISOString(),
    to: to.toISOString(),
    granularity: currentRange === "24h" ? "hour" : "minute",
  };
}

function numberValue(value) {
  const number = Number(value);
  return Number.isFinite(number) ? number : 0;
}

function renderMetrics(data) {
  const values = [
    numberValue(data.total_clicks),
    numberValue(data.avg_clicks_per_minute).toLocaleString("vi-VN", { maximumFractionDigits: 1 }),
    numberValue(data.unique_visitors),
    numberValue(data.flagged_links),
  ];
  document.querySelectorAll("#metrics .kp").forEach((card, index) => {
    const value = card.querySelector(".v");
    value.classList.remove("skeleton");
    value.removeAttribute("aria-label");
    setText(value, values[index] ?? "0");
    const description = card.querySelector(".d");
    if (index === 0) setText(description, `${numberValue(data.total_clicks - data.bot_clicks).toLocaleString("vi-VN")} hợp lệ · ${numberValue(data.bot_clicks).toLocaleString("vi-VN")} bot`);
    if (index === 3 && detailCode) setText(description, "Nhãn tổng hợp chỉ có ở dashboard");
  });
  document.querySelector("#metrics .kp:last-child").hidden = detailCode !== null;
  document.querySelector("#bucket-label").textContent = data.granularity === "hour" ? "giờ" : "phút";
  document.querySelector("#range-label").textContent = ({ "15m": "15 phút", "1h": "60 phút", "24h": "24 giờ" })[currentRange];
}

// API gửi mã quốc gia; trên giao diện người dùng dễ đọc hơn khi thấy tên nước.
function countryName(code) {
  try {
    const names = new Intl.DisplayNames(["vi"], { type: "region" });
    return names.of(code) ?? code;
  } catch {
    return code;
  }
}

function renderCountryBars(rows) {
  const localized = (Array.isArray(rows) ? rows : []).map((row) => ({
    ...row,
    displayName: `${countryName(String(row.name ?? "XX"))} (${String(row.name ?? "XX")})`,
  }));
  renderBars(document.querySelector("#countries-chart"), localized, "displayName");
}

function renderRecentClicks(rows) {
  const target = document.querySelector("#recent-clicks");
  clear(target);
  if (!Array.isArray(rows) || rows.length === 0) {
    target.append(el("div", { className: "table-empty" }, "Chưa có lượt truy cập trong khoảng thời gian đã chọn."));
    return;
  }
  const table = el("table");
  const head = el("thead", {}, el("tr", {},
    el("th", { scope: "col" }, "Thời gian"),
    el("th", { scope: "col" }, "Link"),
    el("th", { scope: "col" }, "Quốc gia"),
    el("th", { scope: "col" }, "Thiết bị"),
    el("th", { scope: "col" }, "Trình duyệt"),
    el("th", { scope: "col" }, "Nguồn"),
    el("th", { scope: "col" }, "Kết quả")));
  const body = el("tbody");
  rows.slice(0, 10).forEach((row) => {
    const code = String(row.code ?? "—");
    const when = new Date(row.timestamp);
    const timeLabel = Number.isNaN(when.getTime()) ? "—" : new Intl.DateTimeFormat("vi-VN", { dateStyle: "short", timeStyle: "medium" }).format(when);
    const result = String(row.result ?? "valid");
    body.append(el("tr", {},
      el("td", {}, timeLabel),
      el("td", {}, el("a", { className: "mono", href: `/dashboard.html?code=${encodeURIComponent(code)}` }, `/${code}`)),
      el("td", {}, countryName(String(row.country ?? "XX"))),
      el("td", {}, String(row.device ?? "—")),
      el("td", {}, String(row.browser ?? "—")),
      el("td", { className: "referrer-cell" }, String(row.referrer ?? "direct")),
      el("td", {}, el("span", { className: `pill ${result === "bot" ? "pill-warning" : "pill-active"}` }, result === "bot" ? "Bot" : "Hợp lệ"))));
  });
  table.append(head, body);
  target.append(table);
}

// Một response cập nhật cùng lúc các thẻ, biểu đồ và bảng để số liệu nhất quán.
function renderData(data) {
  lastData = data;
  renderMetrics(data);
  renderTimeline(document.querySelector("#timeline-chart"), data.timeline);
  document.querySelector("#top-links-chart").closest("article").hidden = Boolean(detailCode);
  renderBars(document.querySelector("#top-links-chart"), data.top_links, "code");
  renderDonut(document.querySelector("#devices-chart"), data.devices);
  renderCountryBars(data.countries);
  renderBars(document.querySelector("#referrers-chart"), data.referrers, "name");
  renderRecentClicks(data.recent_clicks);

  const flaggedLinks = numberValue(data.flagged_links);
  anomalyNotice.hidden = !flaggedLinks;
  if (flaggedLinks) {
    clear(anomalyNotice.querySelector(".notice-content"));
    anomalyNotice.querySelector(".notice-content").append(
      el("strong", {}, `${flaggedLinks} link cần chú ý`),
      document.createTextNode(" đã được hệ thống gắn cờ là đáng ngờ hoặc bị chặn."),
    );
  }

  const timestamp = new Date(data.updated_at);
  const updatedAt = Number.isNaN(timestamp.getTime())
    ? "Dữ liệu vừa cập nhật"
    : `Cập nhật ${new Intl.DateTimeFormat("vi-VN", { hour: "2-digit", minute: "2-digit", second: "2-digit" }).format(timestamp)}`;
  lastUpdatedLabel = `${updatedAt}${isUsingMock() ? " · dữ liệu demo" : ""}`;
  setText(connectionState, lastUpdatedLabel);
  connectionState.classList.add("is-connected");
  notice.hidden = true;
}

function showLoadError(error) {
  notice.hidden = false;
  const message = error instanceof ApiError
    ? getApiErrorMessage(error)
    : "Không thể tải dữ liệu thống kê. Vui lòng thử lại.";
  setText(noticeContent, lastData
    ? `Mất kết nối; đang giữ dữ liệu cũ. ${message}`
    : `Chưa tải được dữ liệu. ${message}`);
  connectionState.classList.remove("is-connected");
  setText(connectionState, lastData ? "Mất kết nối · đang dùng dữ liệu cũ" : "Không thể kết nối");
}

// Giữ nhãn dữ liệu cũ khi polling lỗi để người xem biết dashboard chưa được làm mới.
function updateConnectionState(state) {
  if (state === "loading" && !lastData) setText(connectionState, "Đang tải…");
  else if (state === "loading" && lastData) setText(connectionState, "Đang cập nhật…");
  else if (state === "paused") setText(connectionState, "Tạm dừng khi ẩn tab");
  else if (state === "connected" && lastUpdatedLabel) {
    connectionState.classList.add("is-connected");
    setText(connectionState, lastUpdatedLabel);
  }
}

function restartPolling() {
  poller?.stop();
  poller = createPoller({
    load: async (signal) => {
      const response = await getStats({
        ...rangeOptions(),
        ...(detailCode ? { code: detailCode } : {}),
        signal,
      });
      return response.data;
    },
    onData: renderData,
    onError: showLoadError,
    onState: updateConnectionState,
  });
}

// Bộ lọc chỉ điều hướng; dashboard chi tiết vẫn lấy số liệu từ endpoint theo mã link.
async function loadLinkOptions() {
  if (detailCode) {
    linkSelect.hidden = true;
    return;
  }
  try {
    const response = await getLinks({ limit: 100 });
    const links = Array.isArray(response.data?.items) ? response.data.items : [];
    for (const link of links) {
      const option = el("option", { value: String(link.code ?? "") }, `/${String(link.code ?? "")}`);
      linkSelect.append(option);
    }
  } catch (error) {
    notice.hidden = false;
    notice.className = "notice notice-warning dashboard-notice";
    setText(noticeContent, `Không tải được danh sách link để lọc. ${error instanceof ApiError ? getApiErrorMessage(error) : "Vui lòng thử lại."}`);
  }
}

document.querySelector("#refresh-button").addEventListener("click", () => poller?.refresh());
rangeSelect.addEventListener("click", (event) => {
  const button = event.target.closest("button[data-range]");
  if (!button) return;
  currentRange = button.dataset.range;
  rangeSelect.querySelectorAll("button").forEach((item) => {
    item.classList.toggle("on", item === button);
    item.setAttribute("aria-pressed", String(item === button));
  });
  restartPolling();
});
linkSelect.addEventListener("change", () => {
  const destination = linkSelect.value
    ? `/dashboard.html?code=${encodeURIComponent(linkSelect.value)}`
    : "/dashboard.html";
  window.location.assign(destination);
});

if (detailCode) {
  setText(document.querySelector("h1"), `Thống kê /${detailCode}`);
  document.querySelector("#detail-breadcrumb").hidden = false;
}

loadLinkOptions();
restartPolling();

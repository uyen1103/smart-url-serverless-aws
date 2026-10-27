import { PROTECTION_LAYERS } from "./config.js";
import { getLinks, ApiError, getApiErrorMessage } from "./api.js";
import { clear, el, setText } from "./dom.js";
import { mountShell } from "./shell.js";

mountShell();
const container = document.querySelector("#protection-grid");
const notice = document.querySelector("#protection-notice");
const noticeContent = notice.querySelector(".notice-content");
const flaggedContainer = document.querySelector("#flagged-links");
let flaggedLinks = [];

for (const layer of PROTECTION_LAYERS) {
  const enabled = Boolean(layer.enabled);
  const status = el("span", { className: `status-indicator${enabled ? "" : " off"}`, "aria-hidden": "true" });
  container.append(el("article", { className: "surface protection-item" },
    el("h3", {}, el("span", { className: "feature-check", "aria-hidden": "true" }, enabled ? "✓" : "i"), layer.name),
    el("p", {}, layer.detail),
    el("div", { className: "status-row" },
      status,
      el("span", { className: "status-text" }, enabled ? "Đang áp dụng" : "Chưa xác nhận đã cấu hình"))));
}

// Tóm tắt và danh sách cùng lấy từ API links; màn này chỉ xem, không đổi trạng thái bảo vệ.
function renderMetrics(summary) {
  const cards = [
    { label: "Tổng liên kết", value: summary.total_links, foot: "Thuộc chủ sở hữu này" },
    { label: "Đang hoạt động", value: summary.active_links, foot: "Có thể truy cập bình thường" },
    { label: "Liên kết bị gắn cờ", value: flaggedLinks.length, foot: "Đáng ngờ hoặc bị chặn" },
    { label: "Tổng lượt click", value: summary.total_clicks, foot: "Cộng dồn các liên kết của bạn" },
  ];
  const metrics = document.querySelector("#protection-metrics");
  clear(metrics);
  for (const card of cards) {
    if (card.value === undefined || card.value === null || !Number.isFinite(Number(card.value))) continue;
    metrics.append(el("article", { className: "surface metric-card" },
      el("p", { className: "metric-label" }, card.label),
      el("p", { className: "metric-value" }, Number(card.value).toLocaleString("vi-VN")),
      el("p", { className: "metric-foot" }, card.foot)));
  }
}

function renderFlaggedLinks() {
  clear(flaggedContainer);
  const filter = document.querySelector("#flagged-filter").value;
  const visible = flaggedLinks.filter((link) => !filter || link.status === filter);
  if (!visible.length) {
    flaggedContainer.append(el("div", { className: "table-empty" }, "Không có liên kết thuộc trạng thái này."));
    return;
  }

  const table = el("table");
  table.append(el("thead", {}, el("tr", {},
    el("th", { scope: "col" }, "Liên kết"),
    el("th", { scope: "col" }, "URL đích"),
    el("th", { scope: "col" }, "Click"),
    el("th", { scope: "col" }, "Trạng thái"),
    el("th", { scope: "col" }, el("span", { className: "sr-only" }, "Thống kê")))));
  const body = el("tbody");
  for (const link of visible) {
    const code = String(link.code ?? "");
    const shortUrl = String(link.short_url ?? code);
    const isBlocked = link.status === "blocked";
    body.append(el("tr", {},
      el("td", { className: "link-cell" }, el("a", { className: "mono", href: `/dashboard.html?code=${encodeURIComponent(code)}` }, shortUrl)),
      el("td", { className: "url-cell" }, String(link.long_url ?? "")),
      el("td", { className: "mono" }, Number(link.clicks || 0).toLocaleString("vi-VN")),
      el("td", {}, el("span", { className: `pill ${isBlocked ? "pill-blocked" : "pill-suspicious"}` }, isBlocked ? "Bị chặn" : "Đáng ngờ")),
      el("td", {}, el("a", { className: "btn btn-secondary btn-small", href: `/dashboard.html?code=${encodeURIComponent(code)}` }, "Xem thống kê"))));
  }
  table.append(body);
  flaggedContainer.append(table);
}

async function loadFlaggedLinks(status) {
  const items = [];
  let cursor = "";
  const visitedCursors = new Set();
  do {
    const response = await getLinks({ cursor, limit: 50, status });
    const page = response.data;
    if (!Array.isArray(page?.items)) throw new Error("API danh sách link trả về cấu trúc không hợp lệ.");
    items.push(...page.items);
    cursor = typeof page.next_cursor === "string" ? page.next_cursor : "";
    // Phòng API trả nhầm cursor cũ khiến vòng phân trang chạy mãi.
    if (cursor && visitedCursors.has(cursor)) throw new Error("API trả về cursor phân trang bị lặp.");
    if (cursor) visitedCursors.add(cursor);
  } while (cursor);
  return items;
}

async function loadProtectionData() {
  notice.hidden = true;
  flaggedContainer.replaceChildren(el("div", { className: "loading-row" }, el("span", { className: "spinner" }), "Đang tải liên kết bị gắn cờ…"));
  try {
    const summaryResponse = await getLinks({ limit: 1 });
    const [suspicious, blocked] = await Promise.all([
      loadFlaggedLinks("suspicious"),
      loadFlaggedLinks("blocked"),
    ]);
    flaggedLinks = [
      ...suspicious.map((link) => ({ ...link, status: "suspicious" })),
      ...blocked.map((link) => ({ ...link, status: "blocked" })),
    ];
    renderMetrics(summaryResponse.data?.summary ?? {});
    renderFlaggedLinks();
  } catch (error) {
    notice.hidden = false;
    notice.className = "notice notice-warning section-spacer";
    setText(noticeContent, error instanceof ApiError
      ? getApiErrorMessage(error)
      : "Không thể tải dữ liệu bảo vệ.");
    flaggedContainer.replaceChildren(el("div", { className: "table-empty" }, "Không tải được dữ liệu liên kết."));
  }
}

document.querySelector("#flagged-filter").addEventListener("change", renderFlaggedLinks);
document.querySelector("#protection-retry").addEventListener("click", loadProtectionData);
loadProtectionData();

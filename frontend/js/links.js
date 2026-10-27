import { deleteLink, getLinks, ApiError, getApiErrorMessage, isUsingMock } from "./api.js";
import { clear, el, setText } from "./dom.js";
import { FEATURES } from "./config.js";
import { mountShell, toast, copyText } from "./shell.js";

mountShell();
const target = document.querySelector("#links-table");
const notice = document.querySelector("#links-notice");
const noticeContent = notice.querySelector(".notice-content");
const filterForm = document.querySelector("#filters-form");
const pageSize = 10;
let cursorStack = [""];
let nextCursor = null;
let currentPage = 0;
let currentItems = [];
let loadSequence = 0;

// Mã trạng thái được API quy định; trạng thái lạ vẫn được hiển thị an toàn.
function showError(error) {
  notice.hidden = false;
  const message = error instanceof ApiError ? getApiErrorMessage(error) : "Không thể tải danh sách liên kết.";
  setText(noticeContent, message);
}

function statusLabel(status) {
  const labels = {
    active: ["Đang hoạt động", "pill-active"],
    expired: ["Hết hạn", "pill-expired"],
    max_clicks: ["Đạt giới hạn", "pill-expired"],
    suspicious: ["Đáng ngờ", "pill-suspicious"],
    blocked: ["Bị chặn", "pill-blocked"],
    deleted: ["Đã xóa", "pill-deleted"],
  };
  return Object.hasOwn(labels, status)
    ? labels[status]
    : [String(status ?? "Không rõ"), "pill-expired"];
}

function makeDate(value) {
  if (!value) return "Không giới hạn";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "—" : new Intl.DateTimeFormat("vi-VN", { dateStyle: "medium" }).format(date);
}

function renderLinks(response) {
  notice.hidden = true;
  const data = response.data;
  currentItems = Array.isArray(data?.items) ? data.items : [];
  nextCursor = typeof data?.next_cursor === "string" ? data.next_cursor : null;
  document.querySelector("#previous-page").disabled = currentPage <= 0;
  document.querySelector("#next-page").disabled = !nextCursor;
  setText(document.querySelector("#pagination-info"), currentItems.length
    ? `Trang ${currentPage + 1} · ${currentItems.length} liên kết`
    : "Không có liên kết phù hợp.");
  clear(target);

  if (!currentItems.length) {
    target.append(el("div", { className: "empty-state" },
      el("div", { className: "empty-state-mark", "aria-hidden": "true" }, "↗"),
      el("h2", {}, "Chưa tìm thấy liên kết"),
      el("p", {}, "Thử đổi từ khóa hoặc bộ lọc, hoặc tạo một liên kết mới.")));
    return;
  }

  const table = el("table");
  table.append(el("thead", {}, el("tr", {},
    el("th", { scope: "col" }, "Liên kết"),
    el("th", { scope: "col" }, "URL đích"),
    el("th", { scope: "col" }, "Click"),
    el("th", { scope: "col" }, "Hết hạn"),
    el("th", { scope: "col" }, "Trạng thái"),
    el("th", { scope: "col" }, el("span", { className: "sr-only" }, "Hành động")))));
  const body = el("tbody");
  for (const link of currentItems) {
    const code = String(link.code ?? "");
    const shortUrl = String(link.short_url ?? "");
    const longUrl = String(link.long_url ?? "");
    const [label, className] = statusLabel(link.status);
    const shortLink = el("a", { className: "mono", href: `/${encodeURIComponent(code)}`, title: shortUrl }, shortUrl || code);
    const actions = el("div", { className: "table-actions" });
    const detailButton = el("a", { className: "btn btn-secondary btn-small", href: `/dashboard.html?code=${encodeURIComponent(code)}` }, "Thống kê");
    const copyButton = el("button", { className: "btn btn-secondary btn-small", type: "button" }, "Sao chép");
    copyButton.addEventListener("click", async () => {
      try {
        await copyText(shortUrl);
        toast("Đã sao chép liên kết.");
      } catch {
        toast("Không thể sao chép liên kết. Hãy thử lại trong trình duyệt.", "error");
      }
    });
    actions.append(copyButton, detailButton);
    if (FEATURES.deleteLink && link.status !== "deleted") {
      const deleteButton = el("button", { className: "btn btn-danger btn-small", type: "button", "data-code": code }, "Xóa");
      deleteButton.addEventListener("click", () => removeLink(code, deleteButton));
      actions.append(deleteButton);
    }
    body.append(el("tr", {},
      el("td", { className: "link-cell" }, shortLink, el("span", { className: "muted helper-caption" }, `Tạo ${makeDate(link.created_at)}`)),
      el("td", { className: "url-cell", title: longUrl }, longUrl),
      el("td", { className: "mono" }, Number(link.clicks || 0).toLocaleString("vi-VN")),
      el("td", {}, makeDate(link.expires_at)),
      el("td", {}, el("span", { className: `pill ${className}` }, label)),
      el("td", {}, actions)));
  }
  table.append(body);
  target.append(table);
}

async function loadPage() {
  const sequence = ++loadSequence;
  notice.hidden = true;
  target.replaceChildren(el("div", { className: "loading-row" }, el("span", { className: "spinner" }), "Đang tải danh sách liên kết…"));
  const params = {
    cursor: cursorStack[currentPage],
    limit: pageSize,
    status: document.querySelector("#status-select").value,
    sort: document.querySelector("#sort-select").value,
    query: document.querySelector("#search-input").value.trim(),
  };
  try {
    const response = await getLinks(params);
    // Bỏ response cũ nếu người dùng đã đổi bộ lọc trong lúc request đang chạy.
    if (sequence !== loadSequence) return;
    renderLinks(response);
  } catch (error) {
    if (sequence !== loadSequence) return;
    showError(error);
    target.replaceChildren(el("div", { className: "table-empty" }, "Không thể tải liên kết."));
  }
}

async function removeLink(code, button) {
  // Chỉ gửi yêu cầu xóa sau khi người dùng xác nhận rõ ràng.
  if (!window.confirm(`Xóa liên kết ${code}? Không thể khôi phục sau khi xóa.`)) return;
  button.disabled = true;
  try {
    await deleteLink(code);
    toast("Đã xóa liên kết.");
    await loadPage();
  } catch (error) {
    button.disabled = false;
    toast(error instanceof ApiError ? getApiErrorMessage(error) : "Không thể xóa liên kết.", "error");
  }
}

filterForm.addEventListener("submit", (event) => {
  event.preventDefault();
  cursorStack = [""];
  currentPage = 0;
  loadPage();
});
document.querySelector("#next-page").addEventListener("click", () => {
  if (!nextCursor) return;
  cursorStack.push(nextCursor);
  currentPage += 1;
  loadPage();
});
document.querySelector("#previous-page").addEventListener("click", () => {
  if (currentPage <= 0) return;
  currentPage -= 1;
  loadPage();
});
document.querySelector("#links-retry").addEventListener("click", loadPage);
if (isUsingMock()) {
  const hint = el("span", { className: "pill pill-warning" }, "Dữ liệu demo");
  document.querySelector(".page-heading .heading-actions")?.append(hint);
}
loadPage();

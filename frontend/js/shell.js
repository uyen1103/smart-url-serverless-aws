import { el } from "./dom.js";
import { getOwnerId, isOwnerIdPersistent } from "./owner.js";

const NAV_ITEMS = [
  { href: "/index.html", label: "Rút gọn link", match: ["index.html", ""] },
  { href: "/links.html", label: "Link của tôi", match: ["links.html"] },
  { href: "/dashboard.html", label: "Thống kê", match: ["dashboard.html"] },
  { href: "/protection.html", label: "Chống lạm dụng", match: ["protection.html"] },
];

function logoMark() {
  const icon = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  icon.setAttribute("viewBox", "0 0 24 24");
  icon.setAttribute("fill", "none");
  icon.setAttribute("stroke", "currentColor");
  icon.setAttribute("stroke-width", "2");
  icon.setAttribute("stroke-linecap", "round");
  icon.setAttribute("stroke-linejoin", "round");
  icon.setAttribute("aria-hidden", "true");
  const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
  path.setAttribute("d", "M10 13a5 5 0 0 0 7.5.5l3-3a5 5 0 0 0-7-7L12 5m2 6a5 5 0 0 0-7.5-.5l-3 3a5 5 0 0 0 7 7L12 19");
  icon.append(path);
  return icon;
}

export function mountShell() {
  getOwnerId();
  const header = document.querySelector("[data-site-header]");
  const footer = document.querySelector("[data-site-footer]");
  if (header) {
    const nav = el("div", { className: "nav-wrap" });
    const brand = el("a", { className: "brand", href: "/index.html", "aria-label": "LinkPulse - Trang chủ" },
      el("span", { className: "brand-mark" }, logoMark()),
      el("span", {}, "LinkPulse"));
    const links = el("nav", { className: "nav-links", "aria-label": "Điều hướng chính" });
    const currentPage = window.location.pathname.split("/").pop() || "index.html";
    for (const item of NAV_ITEMS) {
      const link = el("a", { href: item.href }, item.label);
      if (item.match.includes(currentPage)) link.setAttribute("aria-current", "page");
      links.append(link);
    }
    nav.append(
      brand,
      links,
      el("div", { className: "nav-meta" },
        el("span", { className: "environment-status" }, "Hệ thống ổn định")),
    );
    header.replaceChildren(nav);
  }
  if (footer) {
    footer.textContent = `© ${new Date().getFullYear()} LinkPulse · Rút gọn liên kết an toàn`;
  }
  if (!isOwnerIdPersistent()) {
    toast("Trình duyệt không cho lưu mã chủ sở hữu; dữ liệu có thể không còn sau khi tải lại trang.", "error");
  }
}

// Toast chỉ là phản hồi ngắn; nội dung vẫn được thêm dưới dạng text.
export function toast(message, type = "success") {
  const region = document.querySelector("[data-toast-region]");
  if (!region) return;
  const item = el("div", { className: `toast ${type}`, role: "status" }, message);
  region.append(item);
  window.setTimeout(() => item.remove(), 3500);
}

export async function copyText(value) {
  if (navigator.clipboard?.writeText) {
    try {
      await navigator.clipboard.writeText(String(value));
      return;
    } catch {
      // Dùng ô nhập ẩn nếu trình duyệt từ chối Clipboard API.
    }
  }
  // Fallback cho trình duyệt hoặc ngữ cảnh không cấp quyền Clipboard API.
  const temporaryInput = el("textarea", { className: "copy-fallback", readonly: true, "aria-hidden": "true" });
  temporaryInput.value = String(value);
  document.body.append(temporaryInput);
  temporaryInput.select();
  const copied = document.execCommand("copy");
  temporaryInput.remove();
  if (!copied) throw new Error("Trình duyệt không cho phép sao chép.");
}

export function setBusy(button, busy, busyText = "Đang xử lý…") {
  if (busy) {
    button.dataset.originalText = button.textContent;
    button.textContent = busyText;
    button.disabled = true;
    button.setAttribute("aria-busy", "true");
  } else {
    button.textContent = button.dataset.originalText || button.textContent;
    button.disabled = false;
    button.removeAttribute("aria-busy");
  }
}

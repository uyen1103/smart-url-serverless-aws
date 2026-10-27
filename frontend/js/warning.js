import { CONTACT_URL } from "./config.js";
import { el, setPageTitle, setText } from "./dom.js";
import { mountShell } from "./shell.js";

mountShell();
const params = new URLSearchParams(window.location.search);
const reason = params.get("reason");
const code = params.get("code") || "";
const title = document.querySelector("#warning-title");
const message = document.querySelector("#warning-message");
const actions = document.querySelector("#warning-actions");
const codeLabel = document.querySelector("#warning-code");
setText(codeLabel, code ? `Mã liên kết: ${code}` : "");

// Link bị chặn không có nút đi tiếp; chỉ cảnh báo đáng ngờ mới có lựa chọn xác nhận.
if (reason === "blocked") {
  setPageTitle("Liên kết bị chặn");
  setText(title, "Liên kết này đã bị chặn");
  setText(message, "Hệ thống xác định liên kết có thể vi phạm chính sách an toàn. Đích đến đã bị chặn và bạn không thể tiếp tục.");
  actions.append(el("a", { className: "btn btn-primary", href: "/index.html" }, "Về trang chủ"));
} else if (reason === "suspicious") {
  setPageTitle("Liên kết đáng ngờ");
  setText(title, "Liên kết này có dấu hiệu đáng ngờ");
  setText(message, "Hãy kiểm tra kỹ nguồn gửi và địa chỉ đích trước khi tiếp tục. Chỉ tiếp tục nếu bạn tin tưởng liên kết này.");
  if (code) {
    actions.append(el("a", {
      className: "btn btn-danger",
      href: `/${encodeURIComponent(code)}?confirm=1`,
      rel: "nofollow",
    }, "Vẫn tiếp tục"));
  }
  actions.append(el("a", { className: "btn btn-secondary", href: "/index.html" }, "Quay lại nơi an toàn"));
} else {
  setPageTitle("Không tìm thấy cảnh báo");
  setText(title, "Không xác định được loại cảnh báo");
  setText(message, "Liên kết cảnh báo không đầy đủ hoặc không hợp lệ.");
  actions.append(el("a", { className: "btn btn-primary", href: "/index.html" }, "Về trang chủ"));
}

if (CONTACT_URL && reason === "blocked") {
  try {
    const contact = new URL(CONTACT_URL, window.location.origin);
    if (["https:", "mailto:"].includes(contact.protocol)) {
      actions.append(el("a", { className: "btn btn-secondary", href: contact.href }, "Liên hệ hỗ trợ"));
    }
  } catch {
    // Chưa cấu hình URL liên hệ hợp lệ thì không hiển thị hành động.
  }
}

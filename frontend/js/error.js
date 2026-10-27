import { el, setPageTitle, setText } from "./dom.js";
import { mountShell } from "./shell.js";

mountShell();
const params = new URLSearchParams(window.location.search);
const type = params.get("type");
const code = params.get("code") || "";
const title = document.querySelector("#error-title");
const message = document.querySelector("#error-message");
const actions = document.querySelector("#error-actions");
setText(document.querySelector("#error-code"), code ? `Mã liên kết: ${code}` : "");

// Nội dung lấy từ danh sách cho phép, không đưa query string thẳng vào HTML.
const states = {
  "404": {
    title: "Không tìm thấy liên kết",
    message: "Liên kết này không tồn tại hoặc đã bị xóa. Hãy kiểm tra lại đường dẫn.",
  },
  expired: {
    title: "Liên kết đã hết hạn",
    message: "Thời hạn sử dụng của liên kết này đã kết thúc. Hãy liên hệ người gửi để nhận liên kết mới.",
  },
  max_clicks: {
    title: "Liên kết đã đạt giới hạn",
    message: "Liên kết đã đạt số lượt nhấp tối đa do người tạo đặt.",
  },
};
const state = states[type];
if (state) {
  setPageTitle(state.title);
  setText(title, state.title);
  setText(message, state.message);
} else {
  setPageTitle("Liên kết không khả dụng");
  setText(title, "Không xác định được trạng thái liên kết");
  setText(message, "Thông tin lỗi không hợp lệ hoặc đã hết hạn.");
}
actions.append(
  el("a", { className: "btn btn-primary", href: "/index.html" }, "Tạo liên kết mới"),
  el("a", { className: "btn btn-secondary", href: "/links.html" }, "Xem link của tôi"),
);

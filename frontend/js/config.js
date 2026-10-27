// Bật mock để làm giao diện độc lập; chỉ tắt sau khi API môi trường thử nghiệm sẵn sàng.
export const API_BASE_URL = "/api";
export const USE_MOCK = true;
export const TURNSTILE_SITE_KEY = "";
// Dashboard polling theo chu kỳ này; tab ẩn sẽ tạm dừng để tránh request không cần thiết.
export const POLL_INTERVAL_MS = 5000;
export const CONTACT_URL = "";
export const PUBLIC_DOMAIN = "linkpulse.vn";
export const FEATURES = Object.freeze({ deleteLink: true });
export const PROTECTION_LAYERS = Object.freeze([
  { name: "Validate URL", detail: "Chỉ nhận HTTP/HTTPS; backend chặn đích nội bộ.", enabled: true },
  { name: "Rate limit", detail: "Giới hạn request và trả Retry-After khi vượt ngưỡng.", enabled: true },
  { name: "Blocklist", detail: "Từ chối domain đã bị đánh dấu.", enabled: true },
  { name: "Phát hiện link đáng ngờ", detail: "Cảnh báo hoặc yêu cầu xác nhận theo trạng thái backend.", enabled: true },
  { name: "AWS WAF", detail: "Chỉ bật khi hạ tầng xác nhận đã cấu hình.", enabled: false },
]);

// USE_MOCK bật mock mặc định; thêm ?mock=1 để ép chạy mock khi cần kiểm thử.
export function isMockEnabled() {
  return USE_MOCK || new URLSearchParams(window.location.search).get("mock") === "1";
}

// Khi deploy, đổi USE_MOCK=false sau khi API thật và Turnstile đã sẵn sàng.
export const API_BASE_URL = "/api";
export const USE_MOCK = true;
// Khi deploy, điền site key công khai sau khi TV5 bật secret backend đồng thời.
export const TURNSTILE_SITE_KEY = "";
// Dashboard polling theo chu kỳ này; tab ẩn sẽ tạm dừng để tránh request không cần thiết.
export const POLL_INTERVAL_MS = 5000;
export const CONTACT_URL = "https://github.com/uyen1103/smart-url-serverless-aws/issues";
const isLocalhost = ["localhost", "127.0.0.1"].includes(window.location.hostname);
export const PUBLIC_DOMAIN = isLocalhost ? "linkpulse.vn" : window.location.host;
export const FEATURES = Object.freeze({ deleteLink: true });
export const PROTECTION_LAYERS = Object.freeze([
  { name: "Validate URL", detail: "Chỉ nhận HTTP/HTTPS; backend chặn đích nội bộ.", enabled: true },
  { name: "Rate limit", detail: "Giới hạn request và trả Retry-After khi vượt ngưỡng.", enabled: true },
  { name: "Blocklist", detail: "Từ chối domain đã bị đánh dấu.", enabled: true },
  { name: "Phát hiện link đáng ngờ", detail: "Cảnh báo hoặc yêu cầu xác nhận theo trạng thái backend.", enabled: true },
  { name: "AWS WAF", detail: "Chỉ bật khi hạ tầng xác nhận đã cấu hình.", enabled: false },
]);

// Chỉ cho phép ?mock=1 trên máy local; domain deploy luôn tôn trọng USE_MOCK.
export function isMockEnabled() {
  return USE_MOCK || (isLocalhost && new URLSearchParams(window.location.search).get("mock") === "1");
}

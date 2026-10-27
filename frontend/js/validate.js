import { PUBLIC_DOMAIN } from "./config.js";

const RESERVED_ALIASES = new Set([
  "api", "admin", "stats", "links", "home", "protection", "warning", "error",
  "index", "dashboard", "assets", "vendor", "favicon", "mock", "css", "js", "prototype",
]);

// Kiểm tra nhanh ở trình duyệt để báo lỗi sớm; backend vẫn phải xác thực lại.
export function validateUrl(value) {
  const url = String(value ?? "").trim();
  if (!url || url.length > 2048) {
    return { ok: false, message: "Vui lòng nhập URL tối đa 2048 ký tự." };
  }

  let parsed;
  try {
    parsed = new URL(url);
  } catch {
    return { ok: false, message: "URL chưa đúng định dạng. Hãy kiểm tra lại." };
  }

  if (!["http:", "https:"].includes(parsed.protocol)) {
    return { ok: false, message: "URL chỉ được dùng giao thức http:// hoặc https://." };
  }
  if (parsed.username || parsed.password) {
    return { ok: false, message: "URL không được chứa tên đăng nhập hoặc mật khẩu." };
  }

  const host = window.location.hostname.toLowerCase();
  // Chặn cả domain chính và subdomain để tránh tạo vòng lặp qua link của hệ thống.
  const ownHosts = new Set([PUBLIC_DOMAIN.toLowerCase(), host].filter(Boolean));
  if ([...ownHosts].some((ownHost) => parsed.hostname.toLowerCase() === ownHost
    || parsed.hostname.toLowerCase().endsWith(`.${ownHost}`))) {
    return { ok: false, message: "Không thể rút gọn liên kết thuộc chính LinkPulse." };
  }

  return { ok: true, message: "" };
}

export function validateAlias(value) {
  const alias = String(value ?? "").trim();
  if (!alias) {
    return { ok: true, message: "" };
  }
  if (!/^[A-Za-z0-9-]{3,30}$/.test(alias)) {
    return { ok: false, message: "Alias cần có 3–30 ký tự chữ, số hoặc dấu gạch ngang." };
  }
  if (RESERVED_ALIASES.has(alias.toLowerCase())) {
    return { ok: false, message: "Alias này được hệ thống giữ chỗ. Hãy chọn tên khác." };
  }
  return { ok: true, message: "" };
}

export function validateMaxClicks(value) {
  const text = String(value ?? "").trim();
  if (!text) {
    return { ok: true, message: "" };
  }
  if (!/^\d+$/.test(text) || !Number.isSafeInteger(Number(text)) || Number(text) < 1) {
    return { ok: false, message: "Số click tối đa phải là số nguyên từ 1 trở lên." };
  }
  return { ok: true, message: "" };
}

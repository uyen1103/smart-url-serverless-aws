const STORAGE_KEY = "linkpulse-owner-id";
let fallbackOwnerId = "";
let ownerIsPersistent = true;

// Dùng UUID của trình duyệt để nhóm link; đây không phải thông tin đăng nhập.
function createUuid() {
  if (window.crypto?.randomUUID) {
    return window.crypto.randomUUID();
  }

  const bytes = new Uint8Array(16);
  window.crypto.getRandomValues(bytes);
  bytes[6] = (bytes[6] & 0x0f) | 0x40;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;
  const hex = Array.from(bytes, (byte) => byte.toString(16).padStart(2, "0"));
  return `${hex.slice(0, 4).join("")}-${hex.slice(4, 6).join("")}-${hex.slice(6, 8).join("")}-${hex.slice(8, 10).join("")}-${hex.slice(10).join("")}`;
}

export function getOwnerId() {
  try {
    const stored = window.localStorage.getItem(STORAGE_KEY);
    if (stored) {
      return stored;
    }

    const ownerId = createUuid();
    window.localStorage.setItem(STORAGE_KEY, ownerId);
    return ownerId;
  } catch {
    // Một số chế độ riêng tư chặn localStorage; ID tạm dùng đến hết phiên hiện tại.
    ownerIsPersistent = false;
    fallbackOwnerId ||= createUuid();
    return fallbackOwnerId;
  }
}

export function isOwnerIdPersistent() {
  getOwnerId();
  return ownerIsPersistent;
}

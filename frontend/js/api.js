import { API_BASE_URL, isMockEnabled } from "./config.js";
import { getOwnerId } from "./owner.js";
import { validateAlias, validateMaxClicks, validateUrl } from "./validate.js";

const MOCK_LINKS_KEY = "linkpulse-mock-links";
const API_ROOT = API_BASE_URL.replace(/\/+$/, "");
const SCENARIOS = new Set([
  "ok", "duplicate", "invalid_url", "blocked_domain", "alias_taken",
  "rate_limited", "network", "server_error", "waf_html",
]);
const STAT_SCENARIOS = new Set(["normal", "empty", "spike", "suspicious", "network"]);

// Giữ lỗi API theo cùng một dạng để từng trang chỉ cần xử lý theo mã lỗi.
export class ApiError extends Error {
  constructor({ status, code, message, retryAfter = null, retryable = false }) {
    super(message || "Đã xảy ra lỗi khi kết nối dịch vụ.");
    this.name = "ApiError";
    this.status = status;
    this.code = code || "unknown_error";
    this.retryAfter = retryAfter;
    this.retryable = retryable;
  }
}

export function getApiErrorMessage(error) {
  const messages = {
    network_error: "Không thể kết nối máy chủ. Kiểm tra mạng rồi thử lại.",
    timeout: "Máy chủ phản hồi quá lâu. Hãy thử lại.",
    invalid_response: "Máy chủ trả về nội dung không hợp lệ. Vui lòng thử lại sau.",
    invalid_url: "URL không hợp lệ hoặc không được hỗ trợ.",
    blocked_domain: "Domain này không được phép rút gọn.",
    alias_taken: "Alias đã được sử dụng. Hãy chọn tên khác.",
    invalid_alias: "Alias cần có 3–30 ký tự chữ, số hoặc dấu gạch ngang.",
    invalid_max_clicks: "Số click tối đa phải là số nguyên từ 1 trở lên.",
    rate_limited: "Bạn thao tác quá nhanh. Vui lòng chờ rồi thử lại.",
    not_found: "Không tìm thấy liên kết.",
    unauthorized: "Không thể xác thực mã chủ sở hữu của trình duyệt này.",
    forbidden: "Yêu cầu bị từ chối bởi lớp bảo vệ. Hãy kiểm tra thông tin và thử lại.",
    server_error: "Dịch vụ tạm thời không khả dụng. Vui lòng thử lại sau.",
    mock_storage_invalid: "Dữ liệu demo lưu trong trình duyệt bị lỗi. Hãy xóa dữ liệu demo rồi thử lại.",
    storage_unavailable: "Không lưu được dữ liệu demo trong trình duyệt.",
  };
  if (error instanceof ApiError && Object.hasOwn(messages, error.code)) return messages[error.code];
  if (error instanceof ApiError && error.status >= 500) return "Dịch vụ tạm thời không khả dụng. Vui lòng thử lại sau.";
  if (error instanceof ApiError && error.status === 403) return messages.forbidden;
  if (error instanceof ApiError && error.status === 429) return messages.rate_limited;
  return "Không thể hoàn tất yêu cầu. Vui lòng thử lại.";
}

function isRecord(value) {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function normalizeError(status, body, headers) {
  const error = isRecord(body?.error) ? body.error : {};
  const code = typeof error.code === "string" ? error.code : "invalid_response";
  const retryHeader = headers?.get?.("Retry-After");
  const retryAfter = Number.parseInt(retryHeader ?? "", 10);
  return new ApiError({
    status,
    code,
    message: typeof error.message === "string" ? error.message : "Dịch vụ trả về lỗi không xác định.",
    retryAfter: Number.isFinite(retryAfter) && retryAfter >= 0 ? retryAfter : null,
    retryable: status >= 500 || status === 429,
  });
}

// Dùng chung cho request thật: thêm owner ID, giới hạn thời gian chờ và đọc Retry-After.
async function request(path, { method = "GET", body, signal } = {}) {
  const controller = new AbortController();
  const timeoutId = window.setTimeout(() => controller.abort(), 12000);
  const forwardAbort = () => controller.abort();
  if (signal?.aborted) {
    controller.abort();
  } else if (signal) {
    signal.addEventListener("abort", forwardAbort, { once: true });
  }

  try {
    const response = await fetch(`${API_ROOT}${path}`, {
      method,
      signal: controller.signal,
      headers: {
        Accept: "application/json",
        "X-Owner-Id": getOwnerId(),
        ...(body ? { "Content-Type": "application/json" } : {}),
      },
      ...(body ? { body: JSON.stringify(body) } : {}),
    });

    const contentType = response.headers.get("content-type") ?? "";
    if (response.status !== 204 && !contentType.toLowerCase().includes("application/json")) {
      throw new ApiError({
        status: response.status,
        code: "invalid_response",
        message: "Máy chủ trả về nội dung không phải JSON. Vui lòng thử lại sau.",
        retryable: response.status >= 500 || response.status === 403,
      });
    }

    let payload = null;
    if (response.status !== 204) {
      try {
        payload = await response.json();
      } catch {
        throw new ApiError({
          status: response.status,
          code: "invalid_response",
          message: "Máy chủ trả về JSON không hợp lệ. Vui lòng thử lại sau.",
          retryable: response.status >= 500,
        });
      }
    }
    if (!response.ok) {
      throw normalizeError(response.status, payload, response.headers);
    }
    return { data: payload, status: response.status, headers: response.headers };
  } catch (error) {
    if (error instanceof ApiError) {
      throw error;
    }
    const timedOut = error?.name === "AbortError";
    throw new ApiError({
      status: 0,
      code: timedOut ? "timeout" : "network_error",
      message: timedOut
        ? "Máy chủ phản hồi quá lâu. Hãy thử lại."
        : "Không thể kết nối máy chủ. Kiểm tra mạng rồi thử lại.",
      retryable: true,
    });
  } finally {
    window.clearTimeout(timeoutId);
    if (signal) signal.removeEventListener("abort", forwardAbort);
  }
}

async function readJson(path) {
  const response = await fetch(path, { cache: "no-store" });
  if (!response.ok) {
    throw new Error(`Không đọc được dữ liệu mock: ${path} (${response.status}).`);
  }
  return response.json();
}

function delay(milliseconds) {
  return new Promise((resolve) => window.setTimeout(resolve, milliseconds));
}

function selectedScenario() {
  const scenario = new URLSearchParams(window.location.search).get("scenario") || "ok";
  return SCENARIOS.has(scenario) ? scenario : "ok";
}

// Link demo được lưu riêng trong trình duyệt để các lần tải trang vẫn thấy thay đổi.
function getMockLinks() {
  try {
    const stored = window.localStorage.getItem(MOCK_LINKS_KEY);
    if (stored) {
      const links = JSON.parse(stored);
      if (Array.isArray(links)) {
        return links;
      }
      throw new Error("Stored mock link data is not an array.");
    }
  } catch (error) {
    throw new ApiError({
      status: 0,
      code: "mock_storage_invalid",
      message: `Dữ liệu demo lưu trong trình duyệt bị lỗi (${error instanceof Error ? error.message : "không đọc được"}). Hãy xóa linkpulse-mock-links rồi thử lại.`,
    });
  }
  return null;
}

function saveMockLinks(links) {
  try {
    window.localStorage.setItem(MOCK_LINKS_KEY, JSON.stringify(links));
  } catch {
    throw new ApiError({
      status: 0,
      code: "storage_unavailable",
      message: "Không lưu được dữ liệu demo trong trình duyệt.",
    });
  }
}

function createMockCode() {
  const alphabet = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz";
  const bytes = new Uint8Array(7);
  window.crypto.getRandomValues(bytes);
  return Array.from(bytes, (byte) => alphabet[byte % alphabet.length]).join("");
}

async function mockShorten(input) {
  await delay(600 + Math.floor(Math.random() * 301));
  const scenario = selectedScenario();
  const fixture = await readJson(`/mock/scenarios/${scenario}.json`);
  if (fixture.networkError) {
    throw new ApiError({
      status: 0,
      code: "network_error",
      message: "Không thể kết nối máy chủ. Kiểm tra mạng rồi thử lại.",
      retryable: true,
    });
  }
  if (fixture.contentType && !fixture.contentType.toLowerCase().includes("application/json")) {
    throw new ApiError({
      status: fixture.status,
      code: "invalid_response",
      message: "Máy chủ trả về nội dung không phải JSON.",
      retryable: fixture.status >= 500 || fixture.status === 403,
    });
  }
  if (fixture.status !== 200 && fixture.status !== 201) {
    throw new ApiError({
      status: fixture.status,
      code: fixture.body?.error?.code,
      message: fixture.body?.error?.message,
      retryAfter: fixture.retryAfter ?? null,
      retryable: fixture.status >= 500 || fixture.status === 429 || fixture.status === 403,
    });
  }

  const parsedUrl = new URL(input.url);
  const requestedAlias = input.alias?.trim();
  if (scenario === "duplicate") {
    return {
      data: fixture.body,
      status: 200,
      headers: new Headers(),
    };
  }
  const links = getMockLinks() ?? (await readJson("/mock/links.json")).items;
  // Trả mã cũ cho cùng URL trước khi tạo link mới, đúng như hành vi API dự kiến.
  const duplicate = links.find((item) => item.long_url === input.url && item.status !== "deleted");
  const aliasCollision = requestedAlias && links.some((item) => item.code.toLowerCase() === requestedAlias.toLowerCase());
  if (aliasCollision) {
    throw new ApiError({ status: 409, code: "alias_taken", message: "Alias này đã được sử dụng." });
  }

  if (duplicate) {
    return { data: {
      code: duplicate.code,
      short_url: duplicate.short_url,
      long_url: duplicate.long_url,
      created: false,
      expires_at: duplicate.expires_at,
      max_clicks: duplicate.max_clicks,
    }, status: 200, headers: new Headers() };
  }

  const resultCode = requestedAlias || createMockCode();
  const shortUrl = fixture.body.short_url.replace(fixture.body.code, encodeURIComponent(resultCode));
  const created = {
    code: resultCode,
    short_url: shortUrl,
    long_url: parsedUrl.href,
    clicks: 0,
    created_at: new Date().toISOString(),
    expires_at: input.expires_in ? new Date(Date.now() + input.expires_in * 1000).toISOString() : null,
    max_clicks: input.max_clicks ?? null,
    status: "active",
  };
  saveMockLinks([created, ...links]);
  return {
    data: { ...created, created: fixture.body.created !== false },
    status: fixture.status,
    headers: new Headers(),
  };
}

function decodeMockCursor(cursor) {
  if (!cursor) return 0;
  const parsed = Number.parseInt(window.atob(cursor), 10);
  return Number.isSafeInteger(parsed) && parsed >= 0 ? parsed : 0;
}

// Mock cursor chỉ mã hóa vị trí trang; API thật sẽ dùng cursor do backend cấp.
function encodeMockCursor(offset) {
  return window.btoa(String(offset));
}

async function mockGetLinks({ cursor = "", limit = 10, status = "", sort = "created_at_desc", query = "" } = {}) {
  await delay(180);
  const allLinks = getMockLinks() ?? (await readJson("/mock/links.json")).items;
  const links = allLinks
    .filter((item) => !status || item.status === status)
    .filter((item) => !query || item.code.toLowerCase().includes(query.toLowerCase()) || item.long_url.toLowerCase().includes(query.toLowerCase()))
    .sort((left, right) => {
      if (sort === "created_at_asc") return left.created_at.localeCompare(right.created_at);
      if (sort === "clicks_desc") return right.clicks - left.clicks;
      if (sort === "clicks_asc") return left.clicks - right.clicks;
      return right.created_at.localeCompare(left.created_at);
    });
  const start = decodeMockCursor(cursor);
  const items = links.slice(start, start + limit);
  const nextCursor = start + limit < links.length ? encodeMockCursor(start + limit) : null;
  const summary = {
    total_links: allLinks.length,
    active_links: allLinks.filter((item) => item.status === "active").length,
    total_clicks: allLinks.reduce((total, item) => total + Number(item.clicks || 0), 0),
  };
  return { data: { summary, items, next_cursor: nextCursor }, status: 200, headers: new Headers() };
}

async function mockDeleteLink(code) {
  await delay(200);
  const links = getMockLinks() ?? (await readJson("/mock/links.json")).items;
  const remaining = links.filter((item) => item.code !== code);
  if (remaining.length === links.length) {
    throw new ApiError({ status: 404, code: "not_found", message: "Không tìm thấy liên kết." });
  }
  saveMockLinks(remaining);
  return { data: null, status: 204, headers: new Headers() };
}

function dateParameters(options = {}) {
  const params = new URLSearchParams();
  if (options.from) params.set("from", options.from);
  if (options.to) params.set("to", options.to);
  if (options.granularity) params.set("granularity", options.granularity);
  const query = params.toString();
  return query ? `?${query}` : "";
}

async function mockGetStats(options = {}) {
  await delay(250);
  const query = new URLSearchParams(window.location.search);
  const candidate = query.get("statsScenario") || query.get("scenario") || "normal";
  const scenario = STAT_SCENARIOS.has(candidate) ? candidate : "normal";
  if (scenario === "network") {
    throw new ApiError({ status: 0, code: "network_error", message: "Không thể kết nối máy chủ.", retryable: true });
  }
  const path = options.code ? "/mock/stats/suspicious.json" : `/mock/stats/${scenario}.json`;
  const data = await readJson(path);
  const now = new Date().toISOString();
  data.updated_at = now;
  data.from = options.from ?? data.from;
  data.to = options.to ?? now;
  return { data, status: 200, headers: new Headers() };
}

export async function shortenLink(input) {
  const urlResult = validateUrl(input.url);
  if (!urlResult.ok) throw new ApiError({ status: 400, code: "invalid_url", message: urlResult.message });
  const aliasResult = validateAlias(input.alias);
  if (!aliasResult.ok) throw new ApiError({ status: 400, code: "invalid_alias", message: aliasResult.message });
  const clicksResult = validateMaxClicks(input.max_clicks);
  if (!clicksResult.ok) throw new ApiError({ status: 400, code: "invalid_max_clicks", message: clicksResult.message });

  const body = {
    url: input.url.trim(),
    ...(input.alias?.trim() ? { alias: input.alias.trim() } : {}),
    ...(input.expires_in ? { expires_in: Number(input.expires_in) } : {}),
    ...(input.max_clicks ? { max_clicks: Number(input.max_clicks) } : {}),
    ...(input.turnstile_token ? { turnstile_token: input.turnstile_token } : {}),
  };
  return isMockEnabled()
    ? mockShorten(body)
    : request("/shorten", { method: "POST", body });
}

// Giữ tên tham số ở đây khớp API spec để mock và request thật dùng chung giao diện gọi.
export async function getLinks(options = {}) {
  const params = new URLSearchParams();
  if (options.cursor) params.set("cursor", options.cursor);
  if (options.limit) params.set("limit", String(options.limit));
  if (options.status) params.set("status", options.status);
  if (options.sort) params.set("sort", options.sort);
  if (options.query) params.set("q", options.query);
  const query = params.toString();
  return isMockEnabled()
    ? mockGetLinks({ ...options, query: options.query ?? "" })
    : request(`/links${query ? `?${query}` : ""}`);
}

export async function deleteLink(code) {
  return isMockEnabled()
    ? mockDeleteLink(code)
    : request(`/links/${encodeURIComponent(code)}`, { method: "DELETE" });
}

export async function getStats(options = {}) {
  const path = options.code
    ? `/stats/${encodeURIComponent(options.code)}${dateParameters(options)}`
    : `/stats${dateParameters(options)}`;
  return isMockEnabled()
    ? mockGetStats(options)
    : request(path, { signal: options.signal });
}

export function isUsingMock() {
  return isMockEnabled();
}

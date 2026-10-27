const MOCK_SCENARIOS = {
  ok: {
    status: 201,
    body: {
      short_url: "https://linkpulse.vn/aB3kLm9",
      code: "aB3kLm9",
      created: true,
    },
  },
  duplicate: {
    status: 200,
    body: {
      short_url: "https://linkpulse.vn/aB3kLm9",
      code: "aB3kLm9",
      created: false,
    },
  },
  invalid_url: {
    status: 400,
    body: { error: { code: "invalid_url", message: "URL không hợp lệ." } },
  },
  blocked_domain: {
    status: 400,
    body: { error: { code: "blocked_domain", message: "Domain này đang bị chặn." } },
  },
  alias_taken: {
    status: 409,
    body: { error: { code: "alias_taken", message: "Alias này đã được sử dụng." } },
  },
  rate_limited: {
    status: 429,
    retryAfter: 42,
    body: { error: { code: "rate_limited", message: "Bạn thao tác quá nhanh." } },
  },
};

// Mô phỏng API với độ trễ 600–900 ms để demo trạng thái chờ mà không gửi request ra mạng.
function shorten(payload, scenario, ownerId) {
  return new Promise((resolve, reject) => {
    const delay = 600 + Math.floor(Math.random() * 301);
    window.setTimeout(() => {
      if (scenario === "network") {
        reject(new TypeError("Không thể kết nối tới máy chủ."));
        return;
      }

      const result = MOCK_SCENARIOS[scenario] || MOCK_SCENARIOS.ok;
      resolve({
        ...result,
        request: payload,
        headers: { "X-Owner-Id": ownerId },
      });
    }, delay);
  });
}

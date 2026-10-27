import { el, setText } from "./dom.js";
import { ApiError, getApiErrorMessage, isUsingMock, shortenLink } from "./api.js";
import { setBusy, mountShell, toast, copyText } from "./shell.js";
import { validateAlias, validateMaxClicks, validateUrl } from "./validate.js";
import { TURNSTILE_SITE_KEY } from "./config.js";

mountShell();
const demoScenario = document.querySelector("[data-demo-scenario]");
if (demoScenario) {
  const search = new URLSearchParams(window.location.search);
  // Chỉ hiện bộ chọn mock khi chủ động yêu cầu, tránh đưa công cụ kiểm thử vào UI thường.
  demoScenario.hidden = !isUsingMock() || search.get("showDemo") !== "1";
  const scenarioSelect = document.querySelector("#scenario-select");
  const selectedScenario = search.get("scenario");
  if ([...scenarioSelect.options].some((option) => option.value === selectedScenario)) {
    scenarioSelect.value = selectedScenario;
  }
  scenarioSelect.addEventListener("change", () => {
    const url = new URL(window.location.href);
    url.searchParams.set("scenario", scenarioSelect.value);
    window.location.assign(url.href);
  });
}
const form = document.querySelector("#shorten-form");
const submitButton = document.querySelector("#submit-button");
const urlInput = document.querySelector("#url-input");
const aliasInput = document.querySelector("#alias-input");
const maxClicksInput = document.querySelector("#max-clicks-input");
const notice = document.querySelector("#form-notice");
const noticeContent = notice.querySelector(".notice-content");
const resultCard = document.querySelector("#result-card");
let lastSubmission = null;
let countdownTimer = 0;
let turnstileToken = "";

function setFieldError(input, errorNode, message) {
  setText(errorNode, message);
  if (message) input.setAttribute("aria-invalid", "true");
  else input.removeAttribute("aria-invalid");
}

function clearNotice() {
  window.clearInterval(countdownTimer);
  notice.hidden = true;
  notice.className = "notice";
  noticeContent.replaceChildren();
}

function showNotice(type, title, message, retry = false) {
  notice.hidden = false;
  notice.className = `notice notice-${type}`;
  noticeContent.replaceChildren(el("strong", { className: "notice-title" }, title), document.createTextNode(message));
  if (retry) {
    const retryButton = el("button", { className: "btn btn-secondary btn-small", type: "button" }, "Thử lại");
    retryButton.addEventListener("click", () => submitForm(lastSubmission));
    noticeContent.append(document.createTextNode(" "), retryButton);
  }
}

function showRateLimit(seconds) {
  clearNotice();
  notice.hidden = false;
  notice.className = "notice notice-warning";
  let remaining = Math.max(0, seconds);
  submitButton.dataset.rateLimitedUntil = String(Date.now() + remaining * 1000);
  const label = el("span", { className: "notice-content" });
  noticeContent.replaceChildren(el("strong", { className: "notice-title" }, "Bạn thao tác hơi nhanh"));
  noticeContent.append(label);
  const update = () => {
    setText(label, `Vui lòng thử lại sau ${remaining} giây.`);
    submitButton.disabled = remaining > 0;
    if (remaining <= 0) {
      window.clearInterval(countdownTimer);
      setText(label, "Bạn có thể thử tạo liên kết lại.");
    }
    remaining -= 1;
  };
  update();
  countdownTimer = window.setInterval(update, 1000);
}

// Backend trả mã lỗi ổn định; câu chữ trên UI được chọn ở frontend theo mã đó.
function handleApiError(error) {
  if (!(error instanceof ApiError)) {
    showNotice("error", "Không thể hoàn tất yêu cầu", "Đã xảy ra lỗi ngoài dự kiến. Vui lòng tải lại trang và thử lại.", true);
    return;
  }

  if (error.code === "invalid_url") {
    setFieldError(urlInput, document.querySelector("#url-error"), "URL chưa hợp lệ hoặc không được hỗ trợ.");
    urlInput.focus();
    return;
  }
  if (error.code === "blocked_domain") {
    setFieldError(urlInput, document.querySelector("#url-error"), "Domain này không được phép rút gọn.");
    urlInput.focus();
    return;
  }
  if (error.code === "alias_taken") {
    setFieldError(aliasInput, document.querySelector("#alias-error"), "Alias đã được sử dụng. Hãy chọn tên khác.");
    aliasInput.focus();
    return;
  }
  if (error.code === "rate_limited") {
    showRateLimit(error.retryAfter ?? 30);
    return;
  }
  showNotice("error", "Chưa thể tạo liên kết", getApiErrorMessage(error), error.retryable);
}

function renderResult(result, status, input) {
  const duplicate = status === 200 || result.created === false;
  setText(document.querySelector("#result-title"), duplicate
    ? "Liên kết này đã có sẵn trong tài khoản của bạn"
    : "Liên kết đã được tạo");
  const badge = document.querySelector("#result-status");
  setText(badge, duplicate ? "Liên kết cũ" : "Đang hoạt động");
  badge.className = `pill ${duplicate ? "pill-warning" : "pill-active"}`;
  const link = document.querySelector("#short-url");
  let safeShortUrl;
  try {
    safeShortUrl = new URL(result.short_url);
    if (!["http:", "https:"].includes(safeShortUrl.protocol)) throw new Error("Protocol không hợp lệ");
  } catch {
    showNotice("error", "Phản hồi không hợp lệ", "Máy chủ trả về liên kết rút gọn không đúng định dạng.");
    return;
  }
  link.href = safeShortUrl.href;
  link.textContent = safeShortUrl.href;
  const destination = document.querySelector("#result-destination");
  destination.replaceChildren(
    el("span", {}, "Đích đến: "),
    el("span", { className: "mono" }, String(result.long_url ?? input.url)));
  // Nếu response chưa có thời hạn, hiển thị theo tùy chọn người dùng vừa gửi.
  const expiry = result.expires_at
    ? new Date(result.expires_at)
    : input.expires_in
      ? new Date(Date.now() + input.expires_in * 1000)
      : null;
  const expiryLabel = expiry && !Number.isNaN(expiry.getTime())
    ? `Hết hạn: ${new Intl.DateTimeFormat("vi-VN", { dateStyle: "medium", timeStyle: "short" }).format(expiry)}`
    : "Không hết hạn";
  setText(document.querySelector("#result-expiry"), expiryLabel);
  const maxClicks = result.max_clicks ?? input.max_clicks;
  setText(document.querySelector("#result-limit"), maxClicks
    ? `Tối đa ${Number(maxClicks).toLocaleString("vi-VN")} lượt click`
    : "Không giới hạn lượt click");
  resultCard.hidden = false;
  resultCard.scrollIntoView({ behavior: "smooth", block: "nearest" });
}

function collectSubmission() {
  return {
    url: urlInput.value.trim(),
    alias: aliasInput.value.trim(),
    expires_in: form.elements.expiry.value ? Number(form.elements.expiry.value) : null,
    max_clicks: maxClicksInput.value.trim() ? Number(maxClicksInput.value) : null,
    turnstile_token: turnstileToken || undefined,
  };
}

async function submitForm(input = collectSubmission()) {
  if (!input) return;
  const urlResult = validateUrl(input.url);
  const aliasResult = validateAlias(input.alias);
  const clicksResult = validateMaxClicks(input.max_clicks);
  setFieldError(urlInput, document.querySelector("#url-error"), urlResult.message);
  setFieldError(aliasInput, document.querySelector("#alias-error"), aliasResult.message);
  setFieldError(maxClicksInput, document.querySelector("#clicks-error"), clicksResult.message);
  if (!urlResult.ok) return urlInput.focus();
  if (!aliasResult.ok) return aliasInput.focus();
  if (!clicksResult.ok) return maxClicksInput.focus();
  // Không giả lập Turnstile: chỉ chặn gửi khi site key thật đã được cấu hình.
  if (TURNSTILE_SITE_KEY && !turnstileToken) {
    showNotice("warning", "Cần xác minh", "Hoàn tất bước xác minh chống lạm dụng trước khi tiếp tục.");
    return;
  }

  lastSubmission = input;
  resultCard.hidden = true;
  clearNotice();
  setBusy(submitButton, true, "Đang tạo liên kết…");
  try {
    const response = await shortenLink(input);
    renderResult(response.data, response.status, input);
  } catch (error) {
    handleApiError(error);
  } finally {
    setBusy(submitButton, false);
    if (Number(submitButton.dataset.rateLimitedUntil) > Date.now()) {
      submitButton.disabled = true;
    } else {
      delete submitButton.dataset.rateLimitedUntil;
    }
  }
}

form.addEventListener("submit", (event) => {
  event.preventDefault();
  submitForm();
});
document.querySelector("[data-dismiss-notice]").addEventListener("click", clearNotice);
document.querySelector("#copy-button").addEventListener("click", async (event) => {
  const shortUrl = document.querySelector("#short-url").textContent;
  const button = event.currentTarget;
  try {
    await copyText(shortUrl);
    button.textContent = "Đã sao chép";
    toast("Đã sao chép liên kết vào clipboard.");
    window.setTimeout(() => { button.textContent = "Sao chép"; }, 1800);
  } catch {
    toast("Không thể truy cập clipboard. Hãy chọn và sao chép liên kết thủ công.", "error");
  }
});

document.querySelector("#new-link-button").addEventListener("click", () => {
  form.reset();
  resultCard.hidden = true;
  clearNotice();
  for (const [input, selector] of [
    [urlInput, "#url-error"],
    [aliasInput, "#alias-error"],
    [maxClicksInput, "#clicks-error"],
  ]) {
    setFieldError(input, document.querySelector(selector), "");
  }
  urlInput.focus();
});

for (const [input, errorSelector, validator] of [
  [urlInput, "#url-error", validateUrl],
  [aliasInput, "#alias-error", validateAlias],
  [maxClicksInput, "#clicks-error", validateMaxClicks],
]) {
  input.addEventListener("input", () => {
    const result = validator(input.value);
    setFieldError(input, document.querySelector(errorSelector), result.message);
  });
}

if (TURNSTILE_SITE_KEY) {
  const verificationArea = el("div", { className: "field-actions" });
  submitButton.before(verificationArea);
  const note = el("p", { className: "field-hint", role: "status" }, "Đang tải bước xác minh chống lạm dụng…");
  verificationArea.prepend(note);
  const script = el("script", { src: "https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit", async: true, defer: true });
  script.addEventListener("load", () => {
    if (!window.turnstile) {
      setText(note, "Không tải được bước xác minh. Thử tải lại trang.");
      return;
    }
    const container = el("div", { id: "turnstile-widget" });
    verificationArea.prepend(container);
    window.turnstile.render(container, {
      sitekey: TURNSTILE_SITE_KEY,
      callback: (token) => { turnstileToken = token; },
      "expired-callback": () => { turnstileToken = ""; },
    });
    note.remove();
  });
  script.addEventListener("error", () => setText(note, "Không tải được bước xác minh. Kiểm tra kết nối mạng."));
  document.head.append(script);
}

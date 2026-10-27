const form = document.querySelector("#shorten-form");
const urlInput = document.querySelector("#url");
const aliasInput = document.querySelector("#alias");
const clicksInput = document.querySelector("#max-clicks");
const submitButton = document.querySelector("#submit-button");
const formMessage = document.querySelector("#form-message");
const retryButton = document.querySelector("#retry-button");
const resultCard = document.querySelector("#result-card");
const shortUrl = document.querySelector("#short-url");
const resultNote = document.querySelector("#result-note");
const copyButton = document.querySelector("#copy-button");
const copyFeedback = document.querySelector("#copy-feedback");
const scenarioFromQuery = new URLSearchParams(window.location.search).get("scenario");
const supportedScenarios = new Set([
  "ok",
  "duplicate",
  "invalid_url",
  "blocked_domain",
  "alias_taken",
  "rate_limited",
  "network",
]);
const scenario = supportedScenarios.has(scenarioFromQuery) ? scenarioFromQuery : "ok";
let retryTimer = 0;
let fallbackOwnerId = "";

function createOwnerId() {
  if (window.crypto?.randomUUID) {
    return window.crypto.randomUUID();
  }

  return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, (character) => {
    const random = Math.floor(Math.random() * 16);
    const value = character === "x" ? random : (random & 0x3) | 0x8;
    return value.toString(16);
  });
}

function getOwnerId() {
  try {
    const storedOwnerId = window.localStorage.getItem("linkpulse-owner-id");
    if (storedOwnerId) {
      return storedOwnerId;
    }

    const ownerId = createOwnerId();
    window.localStorage.setItem("linkpulse-owner-id", ownerId);
    return ownerId;
  } catch {
    fallbackOwnerId ||= createOwnerId();
    return fallbackOwnerId;
  }
}

function clearFieldErrors() {
  for (const id of ["url-error", "alias-error", "clicks-error"]) {
    document.getElementById(id).textContent = "";
  }
  for (const input of [urlInput, aliasInput, clicksInput]) {
    input.removeAttribute("aria-invalid");
  }
}

function setFieldError(input, messageId, message) {
  input.setAttribute("aria-invalid", "true");
  document.getElementById(messageId).textContent = message;
}

function showMessage(message, tone, canRetry = false) {
  formMessage.textContent = message;
  formMessage.dataset.tone = tone;
  formMessage.hidden = false;
  retryButton.hidden = !canRetry;
}

function hideMessage() {
  formMessage.textContent = "";
  formMessage.hidden = true;
  retryButton.hidden = true;
  delete formMessage.dataset.tone;
}

function validateForm() {
  clearFieldErrors();
  hideMessage();
  resultCard.hidden = true;

  const rawUrl = urlInput.value.trim();
  let valid = true;
  if (!rawUrl || rawUrl.length > 2048) {
    setFieldError(urlInput, "url-error", "Vui lòng nhập URL không quá 2048 ký tự.");
    valid = false;
  } else {
    try {
      const parsedUrl = new URL(rawUrl);
      const isHttp = parsedUrl.protocol === "http:" || parsedUrl.protocol === "https:";
      const host = parsedUrl.hostname.toLowerCase();
      const isOwnDomain = host === "linkpulse.vn" || host.endsWith(".linkpulse.vn");
      if (!isHttp || isOwnDomain) {
        setFieldError(
          urlInput,
          "url-error",
          isOwnDomain
            ? "Không thể rút gọn liên kết thuộc chính LinkPulse."
            : "URL chỉ được dùng giao thức http:// hoặc https://.",
        );
        valid = false;
      }
    } catch {
      setFieldError(urlInput, "url-error", "URL chưa đúng định dạng. Hãy kiểm tra lại.");
      valid = false;
    }
  }

  const alias = aliasInput.value.trim();
  if (alias && !/^[A-Za-z0-9-]{3,30}$/.test(alias)) {
    setFieldError(aliasInput, "alias-error", "Alias cần có 3–30 ký tự chữ, số hoặc dấu gạch ngang.");
    valid = false;
  }

  const maxClicks = clicksInput.value.trim();
  if (maxClicks && (!/^\d+$/.test(maxClicks) || Number(maxClicks) < 1)) {
    setFieldError(clicksInput, "clicks-error", "Số click tối đa phải là số nguyên từ 1 trở lên.");
    valid = false;
  }

  return valid;
}

function setBusy(isBusy) {
  submitButton.disabled = isBusy;
  submitButton.querySelector("span").textContent = isBusy ? "Đang tạo liên kết…" : "Rút gọn liên kết";
}

function showRetryCountdown(seconds) {
  let remaining = seconds;
  submitButton.disabled = true;
  showMessage(`Bạn đã gửi quá nhiều yêu cầu. Vui lòng thử lại sau ${remaining} giây.`, "warning");
  window.clearInterval(retryTimer);
  retryTimer = window.setInterval(() => {
    remaining -= 1;
    if (remaining <= 0) {
      window.clearInterval(retryTimer);
      submitButton.disabled = false;
      showMessage("Bạn có thể thử tạo liên kết lại.", "warning");
      return;
    }
    showMessage(`Bạn đã gửi quá nhiều yêu cầu. Vui lòng thử lại sau ${remaining} giây.`, "warning");
  }, 1000);
}

function showResult(body) {
  shortUrl.textContent = body.short_url;
  resultNote.textContent = body.created
    ? "Bạn có thể sao chép và chia sẻ liên kết này."
    : "URL này đã có trong danh sách của bạn; đây là mã link cũ.";
  copyFeedback.textContent = "";
  resultCard.hidden = false;
}

function handleApiError(result) {
  const code = result.body?.error?.code;
  switch (code) {
    case "invalid_url":
      setFieldError(urlInput, "url-error", "URL không hợp lệ. Chỉ hỗ trợ http:// và https://.");
      break;
    case "blocked_domain":
      setFieldError(urlInput, "url-error", "Domain này bị chặn. Hãy nhập một URL khác.");
      break;
    case "alias_taken":
      setFieldError(aliasInput, "alias-error", "Alias đã được sử dụng. Hãy chọn tên khác.");
      break;
    case "rate_limited":
      showRetryCountdown(result.retryAfter || 1);
      break;
    default:
      showMessage("Máy chủ đang gặp sự cố. Vui lòng thử lại.", "danger", true);
  }
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  window.clearInterval(retryTimer);
  if (!validateForm()) {
    return;
  }

  const expiresIn = document.querySelector("#expires-in").value;
  const payload = {
    url: urlInput.value.trim(),
    alias: aliasInput.value.trim() || undefined,
    expires_in: expiresIn ? Number(expiresIn) : undefined,
    max_clicks: clicksInput.value.trim() ? Number(clicksInput.value) : undefined,
  };
  const ownerId = getOwnerId();

  hideMessage();
  setBusy(true);
  try {
    const result = await shorten(payload, scenario, ownerId);
    if (result.status === 200 || result.status === 201) {
      showResult(result.body);
    } else {
      handleApiError(result);
    }
  } catch {
    showMessage("Không thể kết nối tới máy chủ. Kiểm tra mạng rồi thử lại.", "danger", true);
  } finally {
    setBusy(false);
    if (formMessage.dataset.tone === "warning" && scenario === "rate_limited") {
      submitButton.disabled = true;
    }
  }
});

retryButton.addEventListener("click", () => form.requestSubmit());

copyButton.addEventListener("click", async () => {
  const value = shortUrl.textContent;
  try {
    await navigator.clipboard.writeText(value);
    copyFeedback.textContent = "Đã sao chép";
  } catch {
    copyFeedback.textContent = "Không sao chép tự động được. Hãy chọn và sao chép liên kết.";
  }
});

for (const input of [urlInput, aliasInput, clicksInput]) {
  input.addEventListener("input", () => input.removeAttribute("aria-invalid"));
}

const BLOCKED_ATTRIBUTES = new Set(["innerhtml", "outerhtml", "srcdoc", "formaction"]);

// Chỉ cho phép URL web an toàn vào thuộc tính điều hướng/tài nguyên.
function isSafeUrlAttribute(name, value) {
  if (!["href", "src", "action", "xlink:href"].includes(name.toLowerCase())) {
    return true;
  }
  try {
    const parsed = new URL(String(value).trim(), window.location.origin);
    if (name.toLowerCase() === "href" && parsed.protocol === "mailto:") return true;
    return parsed.protocol === "https:" || parsed.protocol === "http:";
  } catch {
    return false;
  }
}

export function el(tagName, attributes = {}, ...children) {
  const node = document.createElement(tagName);
  for (const [name, value] of Object.entries(attributes ?? {})) {
    const lowerName = name.toLowerCase();
    // Không cho helper tạo thuộc tính có thể chạy script hoặc chèn HTML.
    if (BLOCKED_ATTRIBUTES.has(lowerName) || lowerName.startsWith("on") || value === null || value === undefined) {
      continue;
    }
    if (lowerName === "className".toLowerCase()) {
      node.className = String(value);
      continue;
    }
    if (lowerName === "textContent".toLowerCase()) {
      node.textContent = String(value);
      continue;
    }
    if (!isSafeUrlAttribute(name, value)) {
      continue;
    }
    if (lowerName === "checked" || lowerName === "disabled" || lowerName === "hidden" || lowerName === "required") {
      node[name] = Boolean(value);
    } else {
      node.setAttribute(name, String(value));
    }
  }

  for (const child of children.flat(Infinity)) {
    if (child === null || child === undefined || child === false) {
      continue;
    }
    node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return node;
}

export function text(value) {
  return document.createTextNode(String(value ?? ""));
}

export function setText(node, value) {
  node.textContent = String(value ?? "");
  return node;
}

export function clear(node) {
  node.replaceChildren();
}

export function setPageTitle(title) {
  document.title = `${title} — LinkPulse`;
}

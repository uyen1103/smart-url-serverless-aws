import { el, clear } from "./dom.js";

const SVG_NS = "http://www.w3.org/2000/svg";
const COLORS = ["#6366f1", "#10b981", "#f59e0b", "#ec4899", "#0ea5e9", "#94a3b8"];

// Tạo SVG bằng DOM để dữ liệu biểu đồ không phải ghép thành HTML động.
function svgNode(name, attributes = {}) {
  const node = document.createElementNS(SVG_NS, name);
  for (const [key, value] of Object.entries(attributes)) node.setAttribute(key, String(value));
  return node;
}

function chartEmpty(container, message) {
  clear(container);
  container.append(el("div", { className: "chart-empty" }, message));
}

function finiteNumber(value) {
  const number = Number(value);
  return Number.isFinite(number) ? number : 0;
}

function formatBucket(value) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value ?? "");
  return new Intl.DateTimeFormat("vi-VN", { hour: "2-digit", minute: "2-digit" }).format(date);
}

export function renderTimeline(container, timeline = []) {
  clear(container);
  if (!Array.isArray(timeline) || timeline.length === 0) {
    chartEmpty(container, "Chưa có dữ liệu lượt truy cập trong khoảng thời gian này.");
    return;
  }

  const width = 640;
  const height = 220;
  const pad = { top: 16, right: 15, bottom: 30, left: 36 };
  const chartWidth = width - pad.left - pad.right;
  const chartHeight = height - pad.top - pad.bottom;
  const totalValues = timeline.map((point) => finiteNumber(point.clicks));
  const botValues = timeline.map((point) => finiteNumber(point.bot_clicks));
  // API tính tổng gồm cả bot; phần click hợp lệ là tổng trừ bot.
  const validValues = totalValues.map((value, index) => Math.max(0, value - botValues[index]));
  const max = Math.max(1, ...totalValues);
  const toPoints = (values) => values.map((value, index) => {
    const x = pad.left + (values.length === 1 ? chartWidth / 2 : (index / (values.length - 1)) * chartWidth);
    const y = pad.top + chartHeight - (value / max) * chartHeight;
    return { x, y };
  });
  const points = toPoints(validValues);
  const botPoints = toPoints(botValues);
  const svg = svgNode("svg", {
    class: "chart-svg",
    viewBox: `0 0 ${width} ${height}`,
    role: "img",
    "aria-label": "Biểu đồ đường lượt click theo thời gian",
  });

  for (let i = 0; i <= 4; i += 1) {
    const y = pad.top + (chartHeight / 4) * i;
    svg.append(svgNode("line", { x1: pad.left, y1: y, x2: width - pad.right, y2: y, stroke: "#e2e8f0", "stroke-width": 1 }));
    const label = svgNode("text", { x: 0, y: y + 4, fill: "#64748b", "font-size": 10 });
    label.textContent = String(Math.round(max * (1 - i / 4)));
    svg.append(label);
  }

  const pathData = points.map((point, index) => `${index ? "L" : "M"} ${point.x} ${point.y}`).join(" ");
  const baseline = pad.top + chartHeight;
  const lastPoint = points[points.length - 1];
  const lastBotPoint = botPoints[botPoints.length - 1];
  const areaPath = `${pathData} L ${lastPoint.x} ${baseline} L ${points[0].x} ${baseline} Z`;
  svg.append(svgNode("path", { d: areaPath, fill: COLORS[0], "fill-opacity": .14 }));
  svg.append(svgNode("path", { d: pathData, fill: "none", stroke: COLORS[0], "stroke-width": 2.5, "stroke-linecap": "round", "stroke-linejoin": "round" }));
  const botPathData = botPoints.map((point, index) => `${index ? "L" : "M"} ${point.x} ${point.y}`).join(" ");
  const botAreaPath = `${botPathData} L ${lastBotPoint.x} ${baseline} L ${botPoints[0].x} ${baseline} Z`;
  svg.append(svgNode("path", { d: botAreaPath, fill: COLORS[2], "fill-opacity": .15 }));
  svg.append(svgNode("path", { d: botPathData, fill: "none", stroke: COLORS[2], "stroke-width": 2, "stroke-linecap": "round", "stroke-linejoin": "round" }));
  points.forEach((point, index) => {
    const circle = svgNode("circle", { cx: point.x, cy: point.y, r: 2.5, fill: COLORS[0], stroke: "white", "stroke-width": 1.5 });
    const title = svgNode("title");
    title.textContent = `${formatBucket(timeline[index].bucket)}: ${validValues[index]} click hợp lệ, ${botValues[index]} bot`;
    circle.append(title);
    svg.append(circle);
  });

  const labelIndexes = new Set([0, Math.floor((timeline.length - 1) / 2), timeline.length - 1]);
  labelIndexes.forEach((index) => {
    if (!timeline[index]) return;
    const label = svgNode("text", { x: points[index].x, y: height - 8, fill: "#64748b", "font-size": 10, "text-anchor": "middle" });
    label.textContent = formatBucket(timeline[index].bucket);
    svg.append(label);
  });
  container.append(svg);
}

export function renderBars(container, rows = [], labelKey = "code") {
  clear(container);
  if (!Array.isArray(rows) || rows.length === 0) {
    chartEmpty(container, "Chưa có dữ liệu để hiển thị.");
    return;
  }
  const maximum = Math.max(1, ...rows.map((row) => finiteNumber(row.clicks)));
  const list = el("div", { className: "breakdown-list", role: "list" });
  rows.slice(0, 5).forEach((row) => {
    const name = String(row[labelKey] ?? row.name ?? "Khác");
    const value = finiteNumber(row.clicks);
    const nameNode = labelKey === "code"
      ? el("span", { className: "mono", title: name }, `/${name}`)
      : el("span", { title: name }, name);
    const item = el("div", { className: "bar-row", role: "listitem" },
      nameNode,
      el("span", { className: "bar-track", "aria-hidden": "true" },
        el("span", { className: "bar-fill", style: `width: ${Math.max(1, (value / maximum) * 100)}%` })),
      el("strong", { className: "mono" }, value.toLocaleString("vi-VN")));
    list.append(item);
  });
  container.append(list);
}

export function renderDonut(container, rows = []) {
  clear(container);
  const validRows = Array.isArray(rows) ? rows.filter((row) => finiteNumber(row.clicks) > 0) : [];
  const total = validRows.reduce((sum, row) => sum + finiteNumber(row.clicks), 0);
  if (!total) {
    chartEmpty(container, "Chưa có dữ liệu thiết bị.");
    return;
  }

  const svg = svgNode("svg", { class: "donut-svg", viewBox: "0 0 160 160", role: "img", "aria-label": "Biểu đồ tròn thiết bị" });
  const radius = 55;
  const circumference = 2 * Math.PI * radius;
  let offset = 0;
  // Mỗi lát là một vòng tròn SVG; dash offset đặt lát kế tiếp nối tiếp lát trước.
  validRows.slice(0, COLORS.length).forEach((row, index) => {
    const portion = finiteNumber(row.clicks) / total;
    svg.append(svgNode("circle", {
      cx: 80, cy: 80, r: radius, fill: "none", stroke: COLORS[index],
      "stroke-width": 20, "stroke-dasharray": `${portion * circumference} ${circumference}`,
      "stroke-dashoffset": -offset, transform: "rotate(-90 80 80)",
    }));
    offset += portion * circumference;
  });
  const totalLabel = svgNode("text", { x: 80, y: 76, "text-anchor": "middle", fill: "#0f172a", "font-size": 18, "font-weight": 700 });
  totalLabel.textContent = total.toLocaleString("vi-VN");
  const caption = svgNode("text", { x: 80, y: 96, "text-anchor": "middle", fill: "#64748b", "font-size": 10 });
  caption.textContent = "lượt click";
  svg.append(totalLabel, caption);

  const legend = el("div", { className: "donut-legend" });
  validRows.slice(0, COLORS.length).forEach((row, index) => {
    const label = String(row.name ?? "Khác");
    const item = el("span", { className: "legend-item" },
      el("span", { className: "legend-dot", style: `--legend-color: ${COLORS[index]}` }),
      `${label}: ${Math.round((finiteNumber(row.clicks) / total) * 100)}%`);
    legend.append(item);
  });
  svg.append(svgNode("circle", { cx: 80, cy: 80, r: radius, fill: "none", stroke: "#f1f5f9", "stroke-width": 20 }));
  svg.insertBefore(svg.lastChild, svg.firstChild);
  container.append(el("div", { className: "donut-layout" }, el("div", { className: "donut-graphic" }, svg), legend));
}

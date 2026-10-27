import { POLL_INTERVAL_MS } from "./config.js";

const BACKOFF_MS = [POLL_INTERVAL_MS, 10000, 20000, 30000];

export function createPoller({ load, onData, onError, onState }) {
  let timer = 0;
  let controller = null;
  let failures = 0;
  let stopped = false;
  let busy = false;

  const clearTimer = () => {
    window.clearTimeout(timer);
    timer = 0;
  };

  const schedule = (delay) => {
    clearTimer();
    if (!stopped && document.visibilityState === "visible") {
      timer = window.setTimeout(run, delay);
    }
  };

  async function run() {
    if (stopped || busy || document.visibilityState !== "visible") return;
    busy = true;
    controller = new AbortController();
    onState?.("loading");
    try {
      const data = await load(controller.signal);
      if (stopped || controller.signal.aborted) return;
      failures = 0;
      onData(data);
      onState?.("connected");
    } catch (error) {
      if (!controller.signal.aborted && !stopped) {
        // Tăng thời gian chờ giữa các lần lỗi để không dồn request khi dịch vụ đang trục trặc.
        failures += 1;
        onError(error);
        onState?.("stale");
      }
    } finally {
      busy = false;
      controller = null;
      if (!stopped) schedule(BACKOFF_MS[Math.min(failures, BACKOFF_MS.length - 1)]);
    }
  }

  function onVisibilityChange() {
    if (document.visibilityState === "hidden") {
      // Dừng timer và hủy request hiện tại khi tab không còn được xem.
      clearTimer();
      controller?.abort();
      onState?.("paused");
    } else {
      schedule(0);
    }
  }

  document.addEventListener("visibilitychange", onVisibilityChange);
  run();

  return {
    refresh: () => schedule(0),
    stop: () => {
      stopped = true;
      clearTimer();
      controller?.abort();
      document.removeEventListener("visibilitychange", onVisibilityChange);
    },
  };
}

"""scripts/measure_latency.py: tính phần trăm đúng, chạy được với máy chủ cục bộ, và chặn tải lớn."""
import importlib.util
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from conftest import REPO_ROOT

spec = importlib.util.spec_from_file_location("measure_latency", REPO_ROOT / "scripts" / "measure_latency.py")
ml = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ml)


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    hits = []

    def do_GET(self):
        Handler.hits.append((self.path, self.headers.get("X-Test")))
        status = {"/abc1234": 302, "/loi": 500}.get(self.path, 200)
        time.sleep(0.02 if self.path == "/api/stats" else 0)
        self.send_response(status)
        if status == 302:
            self.send_header("Location", "https://example.com/")
        self.send_header("Content-Length", "2")
        self.end_headers()
        self.wfile.write(b"{}")

    def log_message(self, *_args):
        pass


@pytest.fixture
def server():
    Handler.hits = []
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()


def test_percentile_uses_nearest_rank():
    values = list(range(1, 101))                       # 1..100
    assert [ml.percentile(values, p) for p in (50, 95, 99, 100)] == [50, 95, 99, 100]
    assert ml.percentile([7], 95) == 7 and ml.percentile([1, 2, 3, 4], 50) == 2
    ten = list(range(1, 11))                           # hạng không nguyên: 95% của 10 mẫu phải làm tròn LÊN thành mẫu thứ 10
    assert [ml.percentile(ten, p) for p in (50, 90, 91, 95, 99)] == [5, 9, 10, 10, 10]
    with pytest.raises(ValueError):
        ml.percentile([], 50)


def test_summarize_is_ordered():
    s = ml.summarize([5, 1, 9, 3, 7])
    assert (s["n"], s["min"], s["max"], s["mean"]) == (5, 1, 9, 5) and s["min"] <= s["p50"] <= s["p95"] <= s["p99"] <= s["max"]


def test_measures_every_target_and_does_not_follow_redirects(server, tmp_path, capsys):
    out = tmp_path / "result.json"
    code = ml.main(["--base-url", server, "--code", "abc1234", "--requests", "12", "--delay-ms", "0",
                    "--header", "X-Test: 1", "--json", str(out)])
    assert code == 0
    results = {r["path"]: r for r in json.loads(out.read_text(encoding="utf-8"))["results"]}
    assert set(results) == {"/api/health", "/api/stats", "/abc1234"}
    assert results["/abc1234"]["statuses"] == {"302": 12} and results["/abc1234"]["errors"] == 0   # 302 là thành công
    assert results["/api/stats"]["warm"]["n"] == 11 and results["/api/stats"]["warm"]["p50"] >= 15  # bỏ yêu cầu đầu tiên
    assert all(test_header == "1" for _, test_header in Handler.hits)
    assert "/api/stats" in capsys.readouterr().out


def test_errors_are_counted_and_excluded_from_latency(server, monkeypatch):
    result = ml.measure(server, "/loi", 5, 0, {})
    assert (result["errors"], result["statuses"], result["warm"], result["first_ms"]) == (5, {"500": 5}, None, None)


def test_unreachable_server_is_reported_not_raised():
    result = ml.measure("http://127.0.0.1:9", "/api/health", 3, 0, {}, timeout=1)
    assert (result["errors"], result["statuses"]) == (3, {"None": 3})


@pytest.mark.parametrize("argv", [["--requests", "0"], ["--requests", str(ml.MAX_REQUESTS + 1)], ["--delay-ms", "-1"]])
def test_refuses_large_or_invalid_runs(argv):
    with pytest.raises(SystemExit) as exc:
        ml.parse_args(["--base-url", "http://x", *argv])
    assert exc.value.code == 2

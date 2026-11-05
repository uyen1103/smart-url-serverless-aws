import os
import subprocess
import sys

from conftest import REPO_ROOT


def test_generate_clicks_with_moto_and_seed():
    script = REPO_ROOT / "analytics" / "scripts" / "generate_clicks.py"
    env = os.environ.copy()
    for key in (
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "AWS_SESSION_TOKEN",
        "AWS_PROFILE",
    ):
        env.pop(key, None)

    def run_script():
        return subprocess.run(
            [sys.executable, str(script), "--count", "50", "--seed", "1"],
            cwd=REPO_ROOT,
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=True,
        )

    result = run_script()
    assert result.stdout == run_script().stdout
    assert "Tổng click: 50" in result.stdout
    assert "Số bot:" in result.stdout
    assert "Top referrer:" in result.stdout
    assert "Kiểm tra aggregate(): khớp (50 click)" in result.stdout

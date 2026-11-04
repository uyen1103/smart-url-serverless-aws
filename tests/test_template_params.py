"""Tham số và log group của backend/template.yaml (PR template của TV1, quyết định #3, #7, #18)."""
import yaml

from conftest import TEMPLATE, _CfnLoader


def _template():
    return yaml.load(TEMPLATE.read_text(encoding="utf-8"), Loader=_CfnLoader)


def test_error_page_mode_mac_dinh_la_redirect():
    p = _template()["Parameters"]["ErrorPageMode"]
    assert p["Default"] == "redirect"
    assert set(p["AllowedValues"]) == {"json", "redirect"}


def test_nguong_phat_hien_lam_dung_mac_dinh_va_truyen_vao_process_clicks():
    t = _template()
    assert t["Parameters"]["SpikeClicksPerMinute"]["Default"] == 300
    assert t["Parameters"]["BotMinClicks"]["Default"] == 50
    env = t["Resources"]["ProcessClicksFunction"]["Properties"]["Environment"]["Variables"]
    assert env["SPIKE_CLICKS_PER_MINUTE"] == {"Ref": "SpikeClicksPerMinute"}
    assert env["BOT_MIN_CLICKS"] == {"Ref": "BotMinClicks"}


def test_moi_lambda_co_log_group_giu_7_ngay():
    resources = _template()["Resources"]
    functions = {n for n, r in resources.items() if r["Type"] == "AWS::Serverless::Function"}
    assert len(functions) == 6
    covered = set()
    for r in resources.values():
        if r["Type"] != "AWS::Logs::LogGroup":
            continue
        assert r["Properties"]["RetentionInDays"] == 7
        covered.add(r["Properties"]["LogGroupName"]["Fn::Sub"].removeprefix("/aws/lambda/${").removesuffix("}"))
    assert covered == functions

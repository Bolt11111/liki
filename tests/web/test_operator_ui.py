from pathlib import Path


ROOT = Path(__file__).parents[2]


def test_operator_console_uses_external_same_origin_assets_and_real_endpoints():
    html = (ROOT / "liki/web/index.html").read_text()
    app = (ROOT / "liki/web/app.js").read_text()

    assert 'href="/assets/styles.css"' in html
    assert 'src="/assets/app.js"' in html
    assert "<style" not in html
    assert "<script>" not in html
    for endpoint in (
        "/status", "/requirements", "/scheduler/queues", "/scheduler/why-running",
        "/campaigns", "/paper/status", "/paper/orders", "/governance/proposals",
        "/incidents", "/risk/reservations", "/paper/emergency-stop",
    ):
        assert endpoint in app


def test_operator_console_keeps_token_ephemeral_and_uses_safe_dom_rendering():
    app = (ROOT / "liki/web/app.js").read_text()

    assert "localStorage" not in app
    assert "sessionStorage" not in app
    assert "innerHTML" not in app
    assert "textContent" in app
    assert '"Idempotency-Key"' in app
    assert "accessToken = null" in app

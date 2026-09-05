"""
Phase 1 boundary tests — HTTP edge cases, payload limits, and error contracts.

Every test here corresponds to a behaviour that was reproduced against the
running app during the Phase 1 audit. The docstrings record the observed
pre-fix result, so a regression is recognisable as exactly the old bug.
"""

import glob
import io
import json
import os
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.output.raster_stub import DEFAULT_ZOOM, zoom_for_bbox


def _png_bytes(size=(8, 8)) -> bytes:
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", size, (10, 20, 30)).save(buf, format="PNG")
    return buf.getvalue()


@pytest.fixture
def png():
    return _png_bytes()


@pytest.fixture
def raw_client():
    """TestClient that returns 500s instead of re-raising.

    The shared `client` fixture uses raise_server_exceptions=True, which hides
    exactly the behaviour these tests exist to check: what the *client* sees
    when the handler blows up.
    """
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


def _analyze(client, png, query="What objects are present?", **form):
    data = {"query": query, **form}
    return client.post(
        "/api/analyze",
        data=data,
        files=[("images", ("tiny.png", png, "image/png"))],
    )


def _assert_envelope(res):
    """Every non-2xx body is {"detail": {"errors": [str, ...]}}.

    The API used to speak two dialects: FastAPI's {"detail": [{loc, msg, type}]}
    for framework validation and {"detail": {"errors": [...]}} for hand-raised
    errors, forcing clients to branch on the shape of a failure.
    """
    body = res.json()
    assert isinstance(body, dict), body
    assert set(body) == {"detail"}, body
    detail = body["detail"]
    assert isinstance(detail, dict), detail
    assert isinstance(detail["errors"], list) and detail["errors"], detail
    assert all(isinstance(e, str) for e in detail["errors"]), detail


# ── Crashes that used to be 500s ──────────────────────────────────────────


def test_overlong_filename_is_422_not_500(raw_client, png):
    """Was: 500. tmp_dir / <400-char name> raised OSError: File name too long,
    uncaught, so the client got a plain-text 500 that breaks res.json()."""
    res = raw_client.post(
        "/api/analyze",
        data={"query": "What objects are present?"},
        files=[("images", ("x" * 400 + ".png", png, "image/png"))],
    )
    assert res.status_code == 200, res.text
    # The name is sanitized and truncated, so the upload succeeds rather than
    # being rejected — the point is that it never reaches the filesystem raw.
    assert res.json()["execution_trace"]["input_validation"]["image_count"] == 1


def test_nul_byte_in_filename_is_handled(raw_client, png):
    """A NUL in a path raises ValueError inside open() on every platform."""
    res = raw_client.post(
        "/api/analyze",
        data={"query": "What objects are present?"},
        files=[("images", ("ev\x00il.png", png, "image/png"))],
    )
    assert res.status_code == 200, res.text


def test_unhandled_exception_returns_json_500(raw_client, png, monkeypatch):
    """Was: the plain-text body "Internal Server Error", which is not JSON and
    throws in the frontend's res.json()."""
    import app.output.trace as trace_mod

    def boom(*a, **kw):
        raise RuntimeError("synthetic failure")

    monkeypatch.setattr(trace_mod.TraceBuilder, "build", boom)

    res = _analyze(raw_client, png)
    assert res.status_code == 500
    _assert_envelope(res)
    # The traceback stays server-side.
    assert "synthetic failure" not in res.text
    assert "Traceback" not in res.text


def test_zoom_for_bbox_survives_non_finite_spans():
    """Was: inf -> math.log2(0) -> ValueError -> 500; nan -> 2.0, a
    plausible-looking wrong answer that slipped through min/max."""
    assert zoom_for_bbox({"east": float("inf"), "west": 0.0}) == DEFAULT_ZOOM
    assert zoom_for_bbox({"east": float("nan"), "west": 0.0}) == DEFAULT_ZOOM
    assert zoom_for_bbox({"east": 0.0, "west": float("-inf")}) == DEFAULT_ZOOM
    assert zoom_for_bbox({}) == DEFAULT_ZOOM
    assert zoom_for_bbox({"east": "abc", "west": 0.0}) == DEFAULT_ZOOM
    # A real span still computes normally.
    assert 2.0 <= zoom_for_bbox({"east": 0.01, "west": 0.0}) <= 18.0


def test_health_reports_503_before_the_registry_exists(raw_client, monkeypatch):
    """Was: AttributeError -> 500. An orchestrator kills a pod on 500 and
    merely drains it on 503."""
    monkeypatch.delattr(raw_client.app.state, "model_registry", raising=False)
    res = raw_client.get("/api/health")
    assert res.status_code == 503
    assert res.json()["status"] == "starting"


# ── Information disclosure ────────────────────────────────────────────────


def test_unreadable_image_error_leaks_no_filesystem_path(client, png):
    """Was: the 422 body contained "cannot identify image file
    '/var/folders/.../satquery_xxxx/bad.png'" — the temp-dir scheme, the OS,
    and the account the server runs as."""
    res = client.post(
        "/api/analyze",
        data={"query": "What objects are present?"},
        files=[("images", ("bad.png", b"NOTAPNG" * 40, "image/png"))],
    )
    assert res.status_code == 422
    _assert_envelope(res)
    body = res.text
    for leak in ("/var/", "/tmp/", "satquery_", tempfile.gettempdir()):
        assert leak not in body, f"leaked {leak!r}: {body}"


def test_successful_response_leaks_no_filesystem_path(client, png):
    """The 200 body used to embed the absolute upload path via
    router_metadata.intent_decomposition[].images[].path — the same disclosure
    as the 422 above, on the success path where nobody was looking."""
    res = _analyze(client, png)
    assert res.status_code == 200, res.text
    body = res.text
    for leak in (tempfile.gettempdir(), "/var/folders", "satquery_"):
        assert leak not in body, f"leaked {leak!r}"


# ── Resource exhaustion ───────────────────────────────────────────────────


def test_too_many_images_rejected_before_anything_reaches_disk(client, png, monkeypatch):
    """Was: 20 uploads x 3 MB = 60 MB written to disk before the count check
    ran. Starlette permits 1000 files per request."""
    import app.api.routes as routes

    calls = []
    real_mkdtemp = tempfile.mkdtemp
    monkeypatch.setattr(
        routes.tempfile, "mkdtemp",
        lambda *a, **kw: (calls.append(1), real_mkdtemp(*a, **kw))[1],
    )

    res = client.post(
        "/api/analyze",
        data={"query": "What objects are present?"},
        files=[("images", (f"i{i}.png", png, "image/png")) for i in range(20)],
    )
    assert res.status_code == 422
    _assert_envelope(res)
    assert calls == [], "temp dirs were created before the count check"


def test_oversized_single_image_is_413(client):
    """Pre-existing correct behaviour on /analyze — must not regress."""
    res = client.post(
        "/api/analyze",
        data={"query": "What objects are present?"},
        files=[("images", ("big.png", _png_bytes() + b"\x00" * (52 << 20), "image/png"))],
    )
    assert res.status_code == 413
    _assert_envelope(res)


def test_oversized_content_length_is_rejected_without_reading_the_body(raw_client):
    """The cheap first pass: a declared body over the ceiling is refused before
    the multipart parser is handed anything."""
    res = raw_client.post(
        "/api/analyze",
        content=b"",
        headers={
            "content-length": str(500 * 1024 * 1024),
            "content-type": "multipart/form-data; boundary=x",
        },
    )
    assert res.status_code == 413
    _assert_envelope(res)


def test_malformed_content_length_is_400(raw_client):
    res = raw_client.post(
        "/api/analyze",
        content=b"",
        headers={
            "content-length": "abc",
            "content-type": "multipart/form-data; boundary=x",
        },
    )
    assert res.status_code == 400
    _assert_envelope(res)


def test_oversized_form_field_is_400_not_an_oom(raw_client, png):
    """Requires starlette>=0.40 (CVE-2024-47874). Below that, MultiPartParser
    had no per-part cap and a multi-GB `query` was buffered in memory in full
    before any handler code ran."""
    from starlette.formparsers import MultiPartParser

    assert hasattr(MultiPartParser, "max_part_size"), "starlette<0.40 — CVE-2024-47874"

    res = raw_client.post(
        "/api/analyze",
        data={"query": "a" * (5 * 1024 * 1024)},
        files=[("images", ("tiny.png", png, "image/png"))],
    )
    assert res.status_code == 400
    _assert_envelope(res)


def test_analyze_leaks_no_temp_dirs(client, png):
    """Pre-existing correct behaviour — the `finally` cleanup must not regress."""
    pattern = os.path.join(tempfile.gettempdir(), "satquery_*")
    before = len(glob.glob(pattern))
    for _ in range(3):
        _analyze(client, png)
    assert len(glob.glob(pattern)) == before


# ── /api/process-raster ───────────────────────────────────────────────────


def test_process_raster_leaks_no_temp_dirs(client, png):
    """Was: one leaked temp dir per request, for the process lifetime — this
    route had no cleanup at all, unlike /api/analyze."""
    pattern = os.path.join(tempfile.gettempdir(), "satquery_raster_*")
    before = len(glob.glob(pattern))
    for i in range(3):
        res = client.post(
            "/api/process-raster", files={"image": (f"a{i}.png", png, "image/png")}
        )
        assert res.status_code == 200, res.text
    assert len(glob.glob(pattern)) == before


def test_process_raster_rejects_non_images(client):
    """Was: 200 with a confident-looking bbox near Washington DC and a blank
    grey 512x512 base layer — fabricated geospatial output from garbage."""
    for label, payload in [("junk", b"junkjunk"), ("empty", b"")]:
        res = client.post(
            "/api/process-raster", files={"image": ("a.png", payload, "image/png")}
        )
        assert res.status_code == 422, f"{label}: {res.text}"
        _assert_envelope(res)


def test_process_raster_rejects_unsupported_extension(client, png):
    res = client.post(
        "/api/process-raster", files={"image": ("payload.exe", png, "image/png")}
    )
    assert res.status_code == 422
    _assert_envelope(res)


def test_process_raster_enforces_the_upload_cap(client):
    """Was: 200. MAX_UPLOAD_SIZE_MB was never consulted on this route, and the
    whole body was buffered in memory via `await image.read()`."""
    res = client.post(
        "/api/process-raster",
        files={"image": ("big.png", _png_bytes() + b"\x00" * (52 << 20), "image/png")},
    )
    assert res.status_code == 413
    _assert_envelope(res)


def test_process_raster_still_works_for_a_real_image(client, png):
    res = client.post("/api/process-raster", files={"image": ("a.png", png, "image/png")})
    assert res.status_code == 200, res.text
    body = res.json()
    assert 2.0 <= body["zoom"] <= 18.0
    assert body["bbox"]["north"] > body["bbox"]["south"]


# ── Field validation ──────────────────────────────────────────────────────


def test_empty_modalities_does_not_become_a_modality(client, png):
    '''Was: "".split(",") == [""], so an empty string was carried into the
    execution trace as if it were a real modality.'''
    res = _analyze(client, png, modalities="")
    assert res.status_code == 200, res.text
    assert res.json()["execution_trace"]["input_validation"]["modality"] == ["optical"]


def test_unbounded_modalities_list_is_rejected(client, png):
    """Was: 20 000 comma-separated entries accepted and propagated."""
    res = _analyze(client, png, modalities=",".join(["optical"] * 200))
    assert res.status_code == 422
    _assert_envelope(res)


def test_unknown_modality_is_rejected(client, png):
    """The frontend's own type is Modality = "optical" | "sar"."""
    res = _analyze(client, png, modalities="radar")
    assert res.status_code == 422
    _assert_envelope(res)
    assert "radar" in res.text


def test_modality_case_is_normalized(client, png):
    res = _analyze(client, png, modalities="OPTICAL")
    assert res.status_code == 200, res.text
    assert res.json()["execution_trace"]["input_validation"]["modality"] == ["optical"]


def test_malformed_dates_are_rejected(client, png):
    res = _analyze(client, png, dates="not-a-date")
    assert res.status_code == 422
    _assert_envelope(res)


def test_well_formed_dates_are_accepted(client, png):
    res = _analyze(client, png, dates="2024-01,2024-08")
    assert res.status_code == 200, res.text


def test_overlong_query_is_rejected_at_parse_time(client, png):
    res = _analyze(client, png, query="a" * 5000)
    assert res.status_code == 422
    _assert_envelope(res)


def test_unicode_query_is_accepted(client, png):
    """Non-ASCII must not be mangled or rejected — the product is multilingual
    by intent."""
    res = _analyze(client, png, query="ما هذا \U0001f6f0️ 中文 запрос")
    assert res.status_code == 200, res.text


def test_validator_does_not_mutate_the_reported_modalities(client, png):
    """InputValidator.validate() pads its `modalities` argument in place, which
    mutated the same list the trace reports back as the request's metadata."""
    res = _analyze(client, png, modalities="optical")
    assert res.status_code == 200, res.text
    assert res.json()["execution_trace"]["input_validation"]["modality"] == ["optical"]


# ── Response contract ─────────────────────────────────────────────────────


def test_every_error_response_uses_one_envelope(raw_client, png):
    """Covers both dialects the API used to emit: framework validation errors
    and hand-raised HTTPExceptions."""
    cases = [
        # Framework validation (was {"detail": [{loc, msg, type}]}).
        raw_client.post("/api/analyze", data={"modalities": "optical"}),
        raw_client.post("/api/analyze", data={"query": "hello there"},
                        params={"debug": "notabool"}),
        raw_client.post("/api/process-raster", data={"nope": "1"}),
        # Hand-raised.
        _analyze(raw_client, png, query=""),
        _analyze(raw_client, png, modalities="radar"),
    ]
    for res in cases:
        assert res.status_code >= 400, res.text
        _assert_envelope(res)


def test_validation_errors_do_not_reflect_the_submitted_value(raw_client, png):
    """FastAPI's error entries carry an `input` echoing the client's own value.
    Reflecting a hostile or multi-megabyte field back is not something an error
    path should do."""
    marker = "REFLECTED-MARKER-" + "z" * 64
    res = raw_client.post(
        "/api/analyze", data={"query": "hello there"}, params={"debug": marker}
    )
    assert res.status_code == 422
    assert marker not in res.text


def test_response_never_contains_non_finite_literals(raw_client, png):
    def reject(name):
        raise AssertionError(f"non-finite constant {name!r} leaked into the response")

    res = _analyze(raw_client, png)
    assert res.status_code == 200, res.text
    json.loads(res.text, parse_constant=reject)


def test_json_safe_nulls_non_finite_floats_anywhere():
    """The whole-response backstop for Starlette's allow_nan=False render."""
    from app.output.sanitize import json_safe

    payload = {
        "a": float("nan"),
        "b": [1.0, float("inf"), {"c": float("-inf")}],
        "d": {"e": 0.5},
        "keep": [True, None, "text", 7],
    }
    assert json_safe(payload) == {
        "a": None,
        "b": [1.0, None, {"c": None}],
        "d": {"e": 0.5},
        "keep": [True, None, "text", 7],
    }
    json.dumps(json_safe(payload), allow_nan=False)


# ── Filename sanitizing ───────────────────────────────────────────────────


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("photo.png", "photo.png"),
        ("../../etc/passwd.png", "passwd.png"),
        ("..\\..\\windows\\system32.png", "system32.png"),
        ("", "image_0"),
        (None, "image_0"),
        ("...", "image_0"),
        ("a\x00b.png", "ab.png"),
        # Trailing separators are stripped, so ")" leaves no dangling "_".
        ("scan 01 (final).TIF", "scan_01__final.tif"),
    ],
)
def test_safe_filename(raw, expected):
    from app.api.uploads import safe_filename

    assert safe_filename(raw, 0) == expected


def test_safe_filename_is_length_bounded():
    from app.api.uploads import MAX_STEM_LEN, safe_filename

    out = safe_filename("x" * 500 + ".png", 0)
    assert out == "x" * MAX_STEM_LEN + ".png"
    assert len(out.encode()) < 255


def test_safe_filename_preserves_a_bad_extension_for_the_validator():
    """Coercing an unknown extension to .png would turn a clear "Unsupported
    format" 422 into a confusing "Not a readable image" one."""
    from app.api.uploads import safe_filename

    assert safe_filename("payload.exe", 0) == "payload.exe"

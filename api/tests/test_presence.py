from __future__ import annotations

from app.services.presence import (
    FetchedDoc,
    check_presence,
    control_path_for,
    decide_presence,
)

HOME = b"<!doctype html><html><body>a storefront</body></html>"


def html(url: str, body: bytes = HOME) -> FetchedDoc:
    return FetchedDoc(url=url, status=200, content_type="text/html; charset=utf-8", body=body)


def missing(url: str) -> FetchedDoc:
    return FetchedDoc(url=url, status=404, content_type="text/plain", body=b"not found")


def real_robots(url: str = "https://x.test/robots.txt") -> FetchedDoc:
    return FetchedDoc(url=url, status=200, content_type="text/plain", body=b"User-agent: *\nAllow: /\n")


def test_real_file_is_present():
    v = decide_presence(real_robots(), missing("ctl"))
    assert v.present and bool(v) is True
    assert "text/plain" in v.reason


def test_404_is_absent():
    v = decide_presence(missing("https://x.test/llms.txt"), missing("ctl"))
    assert not v.present and "status 404" in v.reason


def test_html_body_is_absent_even_on_200():
    """The catch-all case that a status check alone gets wrong."""
    v = decide_presence(html("https://x.test/llms.txt"), missing("ctl"))
    assert not v.present and "HTML" in v.reason


def test_identical_to_control_is_absent_even_when_not_html():
    """A catch-all served as text/plain: content-type alone would pass it."""
    body = b"welcome"
    doc = FetchedDoc("https://x.test/llms.txt", 200, "text/plain", body)
    ctl = FetchedDoc("https://x.test/.presence-control-abc.txt", 200, "text/plain", body)
    v = decide_presence(doc, ctl)
    assert not v.present and "byte identical" in v.reason


def test_control_that_404s_does_not_suppress_a_real_file():
    """A well behaved origin: the control 404s and must not affect the verdict."""
    v = decide_presence(real_robots(), missing("ctl"))
    assert v.present


def test_same_length_but_different_bytes_is_present():
    """Guards against comparing by length instead of content."""
    doc = FetchedDoc("https://x.test/llms.txt", 200, "text/plain", b"aaaa")
    ctl = FetchedDoc("https://x.test/ctl", 200, "text/plain", b"bbbb")
    assert decide_presence(doc, ctl).present


def test_content_type_parameters_do_not_defeat_the_html_check():
    doc = FetchedDoc("https://x.test/llms.txt", 200, "TEXT/HTML; charset=UTF-8", b"x")
    assert not decide_presence(doc, missing("ctl")).present


def test_control_path_is_under_the_same_origin_and_random():
    a = control_path_for("https://x.test/some/page")
    b = control_path_for("https://x.test/some/page")
    assert a.startswith("https://x.test/") and a != b


def test_end_to_end_against_a_catch_all_origin():
    """Reproduces the reported behaviour: every path returns the homepage."""
    seen: list[str] = []

    def fetch(url: str) -> FetchedDoc:
        seen.append(url)
        return html(url)

    out = check_presence("https://x.test/", ["robots.txt", "llms.txt", "sitemap.xml"], fetch=fetch)
    assert all(not v.present for v in out.values())
    assert len(seen) == 4, "control should be fetched exactly once, then one fetch per path"


def test_end_to_end_mixed_origin():
    """Real robots.txt, catch-all llms.txt. The audit must separate them."""

    def fetch(url: str) -> FetchedDoc:
        if url.endswith("robots.txt"):
            return real_robots(url)
        if ".presence-control-" in url:
            return html(url)
        return html(url)

    out = check_presence("https://x.test/", ["robots.txt", "llms.txt"], fetch=fetch)
    assert out["robots.txt"].present
    assert not out["llms.txt"].present

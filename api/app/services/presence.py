"""Presence checks that a catch-all route cannot fool.

WHY THIS EXISTS
    "GET the path, HTTP 200 means the file is there" is wrong on any host with a
    catch-all route. Such a host answers 200 for /llms.txt, for /ai.txt and for
    a path that cannot exist, returning the homepage document every time. An
    audit built on the naive check reports files a site does not have, and the
    site owner is told to fix something that is already "fine".

    This is not hypothetical. syntropicsignal.ai itself behaved this way on
    2026-08-10: /llms.txt returned 200 with 194,695 bytes of text/html, byte
    identical to a fetch of /, and so did a random path. Meanwhile /robots.txt
    returned 78 bytes of text/plain and /sitemap-0.xml returned 8,054 bytes of
    text/xml, both distinct. Real files were served correctly. Only missing ones
    fell back to the homepage.

THE THREE SIGNALS, cheapest first
    1. Status is not 2xx                     -> ABSENT
    2. Content-Type is HTML                  -> ABSENT
       A robots.txt, llms.txt or sitemap.xml is never text/html. This alone
       catches most catch-alls and costs nothing extra.
    3. Body is byte identical to a control   -> ABSENT
       The control is a path that cannot exist, fetched once per origin. This
       is the signal that survives hosts which serve their catch-all as
       text/plain, which content-type alone misses.

    A check is only meaningful if it can fail. Fetching the control is what
    makes 200 mean something, so the control is required rather than optional.

DESIGN
    The decision logic is pure and takes already-fetched responses, so it can be
    tested without a network. `check_presence` wires it to httpx for real use.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from typing import Callable, Iterable
from urllib.parse import urljoin, urlparse
import secrets

__all__ = [
    "FetchedDoc",
    "PresenceVerdict",
    "control_path_for",
    "decide_presence",
    "check_presence",
]

HTML_TYPES = ("text/html", "application/xhtml+xml")


@dataclass(frozen=True)
class FetchedDoc:
    """One fetched document, reduced to what a presence decision needs."""

    url: str
    status: int
    content_type: str
    body: bytes

    @property
    def digest(self) -> str:
        return sha256(self.body).hexdigest()

    @property
    def is_html(self) -> bool:
        ct = (self.content_type or "").split(";", 1)[0].strip().lower()
        return ct in HTML_TYPES


@dataclass(frozen=True)
class PresenceVerdict:
    """Present or not, and the reason, so an audit can explain itself."""

    url: str
    present: bool
    reason: str

    def __bool__(self) -> bool:  # lets callers write `if verdict:`
        return self.present


def control_path_for(base_url: str, *, token: str | None = None) -> str:
    """A URL under the same origin that cannot legitimately exist.

    The token is random by default so a host cannot special-case it, and so a
    cached negative from an earlier run cannot be mistaken for a live answer.
    """
    token = token or secrets.token_hex(8)
    return urljoin(base_url, f"/.presence-control-{token}.txt")


def decide_presence(doc: FetchedDoc, control: FetchedDoc) -> PresenceVerdict:
    """Pure decision. `control` is a fetch of a path that cannot exist."""
    if not (200 <= doc.status < 300):
        return PresenceVerdict(doc.url, False, f"status {doc.status}")

    if doc.is_html:
        return PresenceVerdict(
            doc.url, False, f"content-type {doc.content_type!r} is HTML, not a data file"
        )

    if 200 <= control.status < 300 and doc.digest == control.digest:
        return PresenceVerdict(
            doc.url,
            False,
            "body is byte identical to a control path that cannot exist, "
            "so this origin answers 200 for everything",
        )

    return PresenceVerdict(
        doc.url, True, f"status {doc.status}, content-type {doc.content_type!r}, {len(doc.body)} bytes"
    )


def check_presence(
    base_url: str,
    paths: Iterable[str],
    *,
    fetch: Callable[[str], FetchedDoc],
) -> dict[str, PresenceVerdict]:
    """Check several paths against one origin, fetching the control once.

    `fetch` is injected so this stays testable and so callers keep control of
    timeouts, retries, redirects and user-agent.
    """
    origin = f"{urlparse(base_url).scheme}://{urlparse(base_url).netloc}/"
    control = fetch(control_path_for(origin))
    return {p: decide_presence(fetch(urljoin(origin, p)), control) for p in paths}

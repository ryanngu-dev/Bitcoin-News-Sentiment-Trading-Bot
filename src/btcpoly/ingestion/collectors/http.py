from __future__ import annotations

from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from btcpoly.retries import retry


def fetch_bytes(
    url: str,
    *,
    timeout: int,
    headers: dict[str, str] | None = None,
    attempts: int = 2,
) -> bytes:
    req = Request(
        url,
        headers={"User-Agent": "btcpoly/0.1 (research)", **(headers or {})},
    )

    def _get() -> bytes:
        try:
            with urlopen(req, timeout=timeout) as response:
                return response.read()
        except (HTTPError, URLError, TimeoutError, OSError) as exc:
            raise RuntimeError(f"GET {url} failed: {exc}") from exc

    return retry(_get, attempts=attempts, retry_on=(RuntimeError,))


def fetch_text(url: str, *, timeout: int, attempts: int = 2) -> str:
    return fetch_bytes(url, timeout=timeout, attempts=attempts).decode("utf-8", errors="replace")

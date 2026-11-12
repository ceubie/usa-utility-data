"""Real HTTP transport for a live refresh. Tests use a fake instead."""

from collections.abc import Mapping
from urllib.parse import urlencode

import requests

from utilitydata.bronze.drivers.protocol import HttpResponse

USER_AGENT = "utilitydata-refresh"


class RequestsTransport:
    """Send one request and turn a requests timeout into TimeoutError."""

    def request(
        self,
        method: str,
        url: str,
        *,
        params: Mapping[str, str] | None,
        headers: Mapping[str, str] | None,
        data: bytes | None,
        timeout: float,
    ) -> HttpResponse:
        """Perform one request. A timeout is reported as TimeoutError."""
        sent_headers = {"User-Agent": USER_AGENT}
        if headers:
            sent_headers.update(headers)
        body = data
        query = params
        if method.upper() == "POST" and query and body is None:
            body = urlencode(query).encode("utf-8")
            query = None
            sent_headers.setdefault("Content-Type", "application/x-www-form-urlencoded")
        try:
            response = requests.request(
                method,
                url,
                params=query,
                headers=sent_headers,
                data=body,
                timeout=timeout,
            )
        except requests.Timeout as exc:
            raise TimeoutError(str(exc)) from exc
        return HttpResponse(response.status_code, {key: value for key, value in response.headers.items()}, response.content)

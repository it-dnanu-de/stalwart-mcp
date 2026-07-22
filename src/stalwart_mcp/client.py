"""JMAP client for Stalwart mail server management API.

Stalwart v0.16+ exposes management through JMAP (JSON Meta Application Protocol)
at POST /jmap/. All management objects use the "x:" namespace prefix and require
the urn:stalwart:jmap capability.
"""

from __future__ import annotations

import httpx

from .config import get_settings


# JMAP capabilities required for management operations
BASE_CAPABILITIES = [
    "urn:ietf:params:jmap:core",
    "urn:stalwart:jmap",
]

# Additional capabilities that may be needed for specific objects
EXTRA_CAPABILITIES = {
    "principal": ["urn:ietf:params:jmap:principals"],
    "blob": ["urn:ietf:params:jmap:blob"],
    "email": ["urn:ietf:params:jmap:mail"],
}


class JmapError(Exception):
    """Raised when a JMAP method call returns an error."""

    def __init__(self, method: str, error: dict):
        self.method = method
        self.error = error
        super().__init__(f"{method}: {error.get('type', 'unknown')} — {error.get('description', '')}")


class APIError(Exception):
    """Raised when the HTTP request itself fails."""

    def __init__(self, status: int, method: str, path: str, body):
        self.status = status
        self.method = method
        self.path = path
        self.body = body
        super().__init__(f"{method} {path} -> {status}: {body}")


class StalwartClient:
    """JMAP client for Stalwart management API.

    Sends JMAP method calls to POST /jmap/ and parses responses.
    """

    def __init__(
        self,
        base_url: str | None = None,
        token: str | None = None,
        account_id: str = "b",
    ):
        s = get_settings()
        self._base = (base_url or s.stalwart_url).rstrip("/")
        self._token = token or s.stalwart_token
        self._account_id = account_id
        self._call_counter = 0
        self._http = httpx.Client(
            base_url=self._base,
            headers={
                "Authorization": f"Bearer {self._token}",
                "Content-Type": "application/json",
            },
            timeout=30.0,
        )

    # -- low-level HTTP -------------------------------------------------

    def _next_id(self) -> str:
        self._call_counter += 1
        return str(self._call_counter)

    def _handle(self, r: httpx.Response) -> dict:
        if r.status_code >= 400:
            try:
                body = r.json()
            except Exception:
                body = r.text
            raise APIError(r.status_code, r.request.method, str(r.url), body)
        return r.json()

    # -- JMAP request dispatch -------------------------------------------

    def call(
        self,
        method_calls: list,
        using: list[str] | None = None,
    ) -> dict:
        """Send one or more JMAP method calls in a single HTTP request.

        Args:
            method_calls: List of [methodName, params, callId] triples.
            using: JMAP capability URIs. Defaults to core + stalwart management.

        Returns:
            Parsed JSON response with methodResponses key.
        """
        if using is None:
            using = list(BASE_CAPABILITIES)

        payload = {"using": using, "methodCalls": method_calls}
        return self._handle(
            self._http.post(
                f"{self._base}/jmap/",
                json=payload,
            )
        )

    def _build_response_map(self, response: dict) -> dict[str, dict]:
        """Convert methodResponses list to a dict keyed by callId."""
        result = {}
        for resp in response.get("methodResponses", []):
            if len(resp) >= 2:
                method_name = resp[0]
                data = resp[1] if len(resp) > 1 else {}
                call_id = resp[2] if len(resp) > 2 else "?"
                result[call_id] = {
                    "method": method_name,
                    "data": data,
                }
                # Check for JMAP-level error
                if isinstance(data, dict) and data.get("type") and data.get("status"):
                    raise JmapError(method_name, data)
        return result

    def single_call(
        self,
        method: str,
        params: dict,
        using: list[str] | None = None,
    ) -> dict:
        """Send a single JMAP method call and return its response data.

        Args:
            method: JMAP method name, e.g. "x:Account/query".
            params: Method parameters (will have accountId added if absent).
            using: Extra capabilities to merge with defaults.

        Returns:
            The response data for this method call.
        """
        cid = self._next_id()
        if "accountId" not in params:
            params["accountId"] = self._account_id
        if using:
            merged_using = list(BASE_CAPABILITIES)
            for cap in using:
                if cap not in merged_using:
                    merged_using.append(cap)
        else:
            merged_using = None
        response = self.call(
            method_calls=[[method, params, cid]],
            using=merged_using,
        )
        resp_map = self._build_response_map(response)
        return resp_map.get(cid, {}).get("data", {})

    # -- Convenience: query + get in one round-trip ---------------------

    def query_and_get(
        self,
        object_type: str,
        filter: dict | None = None,
        sort: list | None = None,
        limit: int = 25,
        position: int = 0,
        calculate_total: bool = True,
        properties: list[str] | None = None,
        extra_using: list[str] | None = None,
    ) -> dict:
        """Query objects then immediately get their details.

        Uses JMAP back-references so both operations happen in one HTTP round-trip.

        Args:
            object_type: JMAP object type, e.g. "x:Account".
            filter: JMAP filter condition.
            sort: JMAP sort specification.
            limit: Maximum items to return.
            position: Zero-based offset.
            calculate_total: Whether to compute total count.
            properties: List of property names to fetch.
            extra_using: Additional JMAP capabilities.

        Returns:
            Dict with keys: items, total, position, query_state.
        """
        if properties is None:
            properties = ["id"]

        query_id = self._next_id()
        get_id = self._next_id()

        query_params: dict = {
            "accountId": self._account_id,
            "limit": limit,
            "position": position,
            "calculateTotal": calculate_total,
        }
        if filter is not None:
            query_params["filter"] = filter
        if sort is not None:
            query_params["sort"] = sort

        get_params: dict = {
            "accountId": self._account_id,
            "#ids": {
                "resultOf": query_id,
                "name": f"{object_type}/query",
                "path": "/ids",
            },
            "properties": properties,
        }

        merged_using = list(BASE_CAPABILITIES)
        if extra_using:
            for cap in extra_using:
                if cap not in merged_using:
                    merged_using.append(cap)

        response = self.call(
            method_calls=[
                [f"{object_type}/query", query_params, query_id],
                [f"{object_type}/get", get_params, get_id],
            ],
            using=merged_using,
        )

        resp_map = self._build_response_map(response)
        query_data = resp_map.get(query_id, {}).get("data", {})
        get_data = resp_map.get(get_id, {}).get("data", {})

        return {
            "items": get_data.get("list", []),
            "total": query_data.get("total", 0),
            "position": query_data.get("position", 0),
            "query_state": query_data.get("queryState"),
            "not_found": get_data.get("notFound", []),
        }

    # -- Convenience: get by IDs ----------------------------------------

    def get_by_ids(
        self,
        object_type: str,
        ids: list[str],
        properties: list[str] | None = None,
        extra_using: list[str] | None = None,
    ) -> dict:
        """Get objects by their IDs.

        Args:
            object_type: JMAP object type.
            ids: List of object IDs to fetch.
            properties: List of property names to fetch.
            extra_using: Additional JMAP capabilities.

        Returns:
            Dict with keys: items, not_found.
        """
        if properties is None:
            properties = ["id"]

        return self.single_call(
            method=f"{object_type}/get",
            params={
                "ids": ids,
                "properties": properties,
            },
            using=extra_using,
        )

    # -- Convenience: set (create/update/destroy) -----------------------

    def set_objects(
        self,
        object_type: str,
        create: dict | None = None,
        update: dict | None = None,
        destroy: list[str] | None = None,
        extra_using: list[str] | None = None,
    ) -> dict:
        """Create, update, or destroy objects in a single /set call.

        Args:
            object_type: JMAP object type.
            create: Map of tempId -> properties for new objects.
            update: Map of id -> properties to patch.
            destroy: List of IDs to destroy.
            extra_using: Additional JMAP capabilities.

        Returns:
            Dict with keys: created, updated, destroyed, notCreated, notUpdated, notDestroyed.
        """
        params: dict = {}
        if create:
            params["create"] = create
        if update:
            params["update"] = update
        if destroy:
            params["destroy"] = destroy

        return self.single_call(
            method=f"{object_type}/set",
            params=params,
            using=extra_using,
        )

    # -- Health check ---------------------------------------------------

    def health_check(self) -> bool:
        """Check if the JMAP endpoint is reachable by querying principals."""
        try:
            self.query_and_get(
                object_type="x:Account",
                limit=1,
                properties=["id", "name"],
            )
            return True
        except Exception:
            return False

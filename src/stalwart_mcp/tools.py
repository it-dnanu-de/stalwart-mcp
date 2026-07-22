"""MCP tool definitions for Stalwart mail server management via JMAP.

Each tool is a decorated function in a named Group. The server dispatches
by operation name (PascalCase) and calls the function with type-coerced params.
"""

from .client import StalwartClient
from .registry import ROOT, Group, _op

# ── Client singleton ──────────────────────────────────────────────────

_client: StalwartClient | None = None


def _get_client() -> StalwartClient:
    global _client
    if _client is None:
        _client = StalwartClient()
    return _client


def _ok(data):
    if data is None:
        return {"status": "ok"}
    return data


# ── Slim helpers ──────────────────────────────────────────────────────

_DEFAULT_PRINCIPAL_PROPS = ["id", "name", "description", "emailAddress", "roles", "createdAt"]


def _slim(item: dict, fields: set) -> dict:
    return {k: v for k, v in item.items() if k in fields}


def _slim_list(items: list, fields: set) -> list:
    return [_slim(i, fields) for i in items if isinstance(i, dict)]


# ── Unavailable operation marker ──────────────────────────────────────

def _unavailable(operation: str, reason: str) -> dict:
    """Return a structured unavailable response for operations
    that have no JMAP equivalent in Stalwart Community Edition."""
    return {
        "error": f"{operation} is not available via JMAP management API.",
        "reason": reason,
        "suggestion": "Use the Stalwart WebAdmin at /account for this operation.",
    }


# ── Groups ────────────────────────────────────────────────────────────

stalwart_read = Group(
    "stalwart_read",
    "Query Stalwart mail server data (safe, read-only).\n\n"
    "Call with operation=\"help\" to list all available read operations.\n"
    "Otherwise pass the operation name and a JSON object with parameters.\n\n"
    "Example: stalwart_read(operation=\"ListPrincipals\", "
    "params={\"types\": \"individual\", \"limit\": 20})",
)

stalwart_write = Group(
    "stalwart_write",
    "Create or update Stalwart resources (non-destructive).\n\n"
    "Call with operation=\"help\" to list all available write operations.\n"
    "Otherwise pass the operation name and a JSON object with parameters.\n\n"
    "Example: stalwart_write(operation=\"CreatePrincipal\", "
    "params={\"type\": \"individual\", \"name\": \"user@example.com\"})",
)

stalwart_delete = Group(
    "stalwart_delete",
    "Delete Stalwart resources (destructive, irreversible).\n\n"
    "Call with operation=\"help\" to list all available delete operations.\n"
    "Otherwise pass the operation name and a JSON object with parameters.\n\n"
    "Example: stalwart_delete(operation=\"DeletePrincipal\", "
    "params={\"id\": \"user@example.com\"})",
)

stalwart_admin = Group(
    "stalwart_admin",
    "Stalwart admin operations: reload, updates, diagnostics, maintenance.\n\n"
    "Call with operation=\"help\" to list all available admin operations.\n"
    "Otherwise pass the operation name and a JSON object with parameters.\n\n"
    "Example: stalwart_admin(operation=\"ReloadConfig\", params={\"dry_run\": true})",
)


# ── ROOT ──────────────────────────────────────────────────────────────

@_op(ROOT)
def stalwart_version():
    """Get the Stalwart MCP server version and service status."""
    from importlib.metadata import version

    try:
        client = _get_client()
        result = client.query_and_get(
            object_type="x:Account",
            limit=1,
            properties=["id", "name"],
        )
        service = {
            "status": "ok",
            "account_count": result.get("total", 0),
        }
    except Exception as exc:
        service = {"status": "error", "detail": str(exc)}
    return {"mcp": version("stalwart-mcp"), "service": service}


# ── stalwart_read ─────────────────────────────────────────────────────

@_op(stalwart_read)
def list_principals(
    types: str | None = None,
    page: int | None = None,
    limit: int = 20,
):
    """List principals (accounts). types filter: individual, group, list, domain, tenant, role, apiKey, oauthClient."""
    position = 0
    if page is not None and page > 0:
        position = (page - 1) * limit

    filter_dict = None
    if types is not None:
        type_list = [t.strip() for t in types.split(",")]
        filter_dict = {"type": type_list}

    result = _get_client().query_and_get(
        object_type="x:Account",
        filter=filter_dict,
        limit=limit,
        position=position,
        properties=["id", "name", "description", "emailAddress", "roles", "createdAt"],
    )

    items = _slim_list(result.get("items", []), _DEFAULT_PRINCIPAL_PROPS)
    return {
        "items": items,
        "total": result.get("total", 0),
        "page": page or 1,
        "limit": limit,
    }


@_op(stalwart_read)
def show_principal(id: str):
    """Get full principal details by ID."""
    result = _get_client().get_by_ids(
        object_type="x:Account",
        ids=[id],
        properties=[
            "id", "name", "description", "emailAddress", "roles",
            "memberOf", "enabledPermissions", "disabledPermissions",
            "createdAt", "quota",
        ],
    )
    items = result.get("list", [])
    if items:
        return items[0]
    return {"error": f"Principal {id} not found.", "not_found": result.get("notFound", [id])}


@_op(stalwart_read)
def get_queue_status():
    """Get mail queue processing status (count of queued messages)."""
    result = _get_client().query_and_get(
        object_type="x:QueuedMessage",
        limit=1,
        calculate_total=True,
        properties=["id"],
    )
    return {
        "queued_count": result.get("total", 0),
        "status": "ok",
    }


@_op(stalwart_read)
def list_queue_messages(
    page: int | None = None,
    limit: int = 20,
    values: str | None = None,
):
    """List queued messages. values: filter string (searches return path, sender, recipient)."""
    position = 0
    if page is not None and page > 0:
        position = (page - 1) * limit

    filter_dict = None
    if values is not None:
        filter_dict = {"text": values}

    result = _get_client().query_and_get(
        object_type="x:QueuedMessage",
        filter=filter_dict,
        limit=limit,
        position=position,
        properties=["id", "returnPath", "nextRetry", "createdAt", "size", "status"],
    )
    return {
        "items": result.get("items", []),
        "total": result.get("total", 0),
        "page": page or 1,
        "limit": limit,
    }


@_op(stalwart_read)
def show_queue_message(id: str):
    """Get full details of a queued message by ID."""
    result = _get_client().get_by_ids(
        object_type="x:QueuedMessage",
        ids=[id],
        properties=[
            "id", "returnPath", "nextRetry", "createdAt", "size",
            "status", "priority", "envId", "from", "to",
            "subject", "receivedAt", "queueId", "retryCount",
        ],
    )
    items = result.get("list", [])
    if items:
        return items[0]
    return {"error": f"Queued message {id} not found."}


@_op(stalwart_read)
def list_queued_reports(
    page: int | None = None,
    limit: int = 20,
):
    """List queued delivery reports."""
    return _unavailable(
        "ListQueuedReports",
        "Delivery reports are available via x:InboxReport and x:OutboxReport "
        "management objects. Use ListInboxReports or ListOutboxReports instead.",
    )


@_op(stalwart_read)
def list_inbox_reports(
    page: int | None = None,
    limit: int = 20,
):
    """List incoming DMARC/TLS/ARF reports."""
    position = 0
    if page is not None and page > 0:
        position = (page - 1) * limit

    result = _get_client().query_and_get(
        object_type="x:InboxReport",
        limit=limit,
        position=position,
        properties=["id", "type", "timestamp", "subject", "from"],
    )
    return {
        "items": result.get("items", []),
        "total": result.get("total", 0),
        "page": page or 1,
        "limit": limit,
    }


@_op(stalwart_read)
def list_outbox_reports(
    page: int | None = None,
    limit: int = 20,
):
    """List outgoing DMARC/TLS reports."""
    position = 0
    if page is not None and page > 0:
        position = (page - 1) * limit

    result = _get_client().query_and_get(
        object_type="x:OutboxReport",
        limit=limit,
        position=position,
        properties=["id", "type", "timestamp", "subject", "to"],
    )
    return {
        "items": result.get("items", []),
        "total": result.get("total", 0),
        "page": page or 1,
        "limit": limit,
    }


@_op(stalwart_read)
def list_dmarc_reports(
    page: int | None = None,
    limit: int = 20,
):
    """List incoming DMARC reports. Redirects to ListInboxReports."""
    result = list_inbox_reports(page=page, limit=limit)
    if "items" in result:
        result["note"] = "Filter by type='dmarc' for DMARC-only reports."
    return result


@_op(stalwart_read)
def list_tls_reports(
    page: int | None = None,
    limit: int = 20,
):
    """List incoming TLS reports. Redirects to ListInboxReports."""
    result = list_inbox_reports(page=page, limit=limit)
    if "items" in result:
        result["note"] = "Filter by type='tlsrpt' for TLS-only reports."
    return result


@_op(stalwart_read)
def list_arf_reports(
    page: int | None = None,
    limit: int = 20,
):
    """List incoming ARF/abuse reports. Redirects to ListInboxReports."""
    result = list_inbox_reports(page=page, limit=limit)
    if "items" in result:
        result["note"] = "Filter by type='arf' for ARF-only reports."
    return result


@_op(stalwart_read)
def get_settings_by_keys(
    keys: list | None = None,
    prefixes: list | None = None,
):
    """Get system settings. Pass property names as keys list to filter which settings to return."""
    properties = [
        "id", "defaultHostname", "defaultDomainId", "defaultCertificateId",
        "maxConnections", "threadPoolSize", "proxyTrustedNetworks",
    ]
    if keys is not None:
        properties = [k for k in keys if isinstance(k, str)]

    result = _get_client().get_by_ids(
        object_type="x:SystemSettings",
        ids=["singleton"],
        properties=properties,
    )
    items = result.get("list", [])
    if items:
        return items[0]
    return {"error": "SystemSettings singleton not found."}


@_op(stalwart_read)
def get_settings_by_group(
    prefix: str | None = None,
    suffix: str | None = None,
    page: int | None = None,
    limit: int = 20,
):
    """Get settings by group prefix/suffix. Returns all matching settings.

    prefix: e.g. 'network', 'storage', 'authentication', 'tls', 'mta',
            'cluster', 'spam', 'email', 'calendar', 'sieve', 'security',
            'lookup', 'search', 'telemetry', 'ai', 'enterprise'
    """
    # Map common prefixes to SystemSettings property groups
    prefix_to_props = {
        "network": ["defaultHostname", "defaultDomainId", "defaultCertificateId",
                     "maxConnections", "threadPoolSize", "proxyTrustedNetworks"],
        "tls": ["defaultCertificateId"],
        "mta": ["defaultHostname", "defaultDomainId"],
        "spam": [],
        "email": [],
        "storage": [],
        "authentication": [],
        "cluster": [],
        "calendar": [],
        "sieve": [],
        "security": [],
        "lookup": [],
        "search": [],
        "telemetry": [],
        "ai": [],
        "enterprise": [],
    }
    properties = prefix_to_props.get(prefix or "", ["id", "defaultHostname",
        "defaultDomainId", "defaultCertificateId", "maxConnections",
        "threadPoolSize", "proxyTrustedNetworks"])

    result = _get_client().get_by_ids(
        object_type="x:SystemSettings",
        ids=["singleton"],
        properties=properties,
    )
    items = result.get("list", [])
    if items:
        data = items[0]
        if suffix:
            matching = {k: v for k, v in data.items() if suffix.lower() in k.lower()}
            return matching
        return data
    return {"error": "SystemSettings singleton not found."}


@_op(stalwart_read)
def list_settings(prefix: str | None = None):
    """List all settings, optionally filtered by prefix."""
    props = ["id", "defaultHostname", "defaultDomainId", "defaultCertificateId",
             "maxConnections", "threadPoolSize", "proxyTrustedNetworks"]
    result = _get_client().get_by_ids(
        object_type="x:SystemSettings",
        ids=["singleton"],
        properties=props,
    )
    items = result.get("list", [])
    if items:
        data = items[0]
        if prefix:
            matching = {k: v for k, v in data.items() if k.lower().startswith(prefix.lower())}
            return matching
        return data
    return {"error": "SystemSettings singleton not found."}


@_op(stalwart_read)
def list_logs(
    page: int | None = None,
    limit: int = 20,
):
    """List server log entries."""
    position = 0
    if page is not None and page > 0:
        position = (page - 1) * limit

    result = _get_client().query_and_get(
        object_type="x:Log",
        limit=limit,
        position=position,
        properties=["id", "timestamp", "level", "event", "details"],
    )
    return {
        "items": result.get("items", []),
        "total": result.get("total", 0),
        "page": page or 1,
        "limit": limit,
    }


@_op(stalwart_read)
def list_metrics():
    """List telemetry metrics from current live metrics."""
    return _unavailable(
        "ListMetrics",
        "Live metrics streaming uses server-sent events, not JMAP. "
        "Use the WebAdmin Observability section or check /api/schema for available metrics.",
    )


@_op(stalwart_read)
def list_traces(
    type: str | None = None,
    page: int | None = None,
    limit: int = 20,
):
    """List live tracing sessions."""
    position = 0
    if page is not None and page > 0:
        position = (page - 1) * limit

    result = _get_client().query_and_get(
        object_type="x:LiveTrace",
        limit=limit,
        position=position,
        properties=["id", "type", "startedAt", "status"],
    )
    return {
        "items": result.get("items", []),
        "total": result.get("total", 0),
        "page": page or 1,
        "limit": limit,
    }


@_op(stalwart_read)
def show_trace(id: str):
    """Get full trace details by ID."""
    result = _get_client().get_by_ids(
        object_type="x:LiveTrace",
        ids=[id],
        properties=["id", "type", "startedAt", "status", "filter", "duration"],
    )
    items = result.get("list", [])
    if items:
        return items[0]
    return {"error": f"Trace {id} not found."}


@_op(stalwart_read)
def list_domains(
    page: int | None = None,
    limit: int = 20,
):
    """List managed domains."""
    position = 0
    if page is not None and page > 0:
        position = (page - 1) * limit

    result = _get_client().query_and_get(
        object_type="x:Domain",
        limit=limit,
        position=position,
        properties=["id", "name"],
    )
    return {
        "items": result.get("items", []),
        "total": result.get("total", 0),
        "page": page or 1,
        "limit": limit,
    }


@_op(stalwart_read)
def list_dkim_signatures(
    page: int | None = None,
    limit: int = 20,
):
    """List DKIM signatures."""
    position = 0
    if page is not None and page > 0:
        position = (page - 1) * limit

    result = _get_client().query_and_get(
        object_type="x:DkimSignature",
        limit=limit,
        position=position,
        properties=["id", "selector", "createdAt", "stage"],
    )
    return {
        "items": result.get("items", []),
        "total": result.get("total", 0),
        "page": page or 1,
        "limit": limit,
    }


@_op(stalwart_read)
def get_dns_records(domain: str):
    """Get DNS records for a domain. Returns domain information from Stalwart."""
    result = _get_client().query_and_get(
        object_type="x:Domain",
        filter={"name": domain},
        limit=1,
        properties=["id", "name"],
    )
    items = result.get("items", [])
    if items:
        return items[0]
    return {"error": f"Domain {domain} not found in Stalwart."}


@_op(stalwart_read)
def list_certificates(
    page: int | None = None,
    limit: int = 20,
):
    """List TLS certificates."""
    position = 0
    if page is not None and page > 0:
        position = (page - 1) * limit

    result = _get_client().query_and_get(
        object_type="x:Certificate",
        limit=limit,
        position=position,
        properties=["id", "subjectAlternativeNames", "issuer", "notBefore", "notAfter"],
    )
    return {
        "items": result.get("items", []),
        "total": result.get("total", 0),
        "page": page or 1,
        "limit": limit,
    }


@_op(stalwart_read)
def list_deleted_messages(
    account_id: str,
    page: int | None = None,
    limit: int = 20,
):
    """List deleted messages for an account (available for restore)."""
    return _unavailable(
        "ListDeletedMessages",
        "Undelete/restore has no JMAP management endpoint in Stalwart v0.16. "
        "Use the WebAdmin or IMAP to manage deleted messages.",
    )


@_op(stalwart_read)
def get_blob(blob_id: str, limit: int | None = None):
    """Get raw blob content by ID."""
    return _unavailable(
        "GetBlob",
        "Blob retrieval via JMAP is not available for management accounts. "
        "Use the WebAdmin for blob inspection.",
    )


@_op(stalwart_read)
def list_groups(
    page: int | None = None,
    limit: int = 20,
):
    """List groups (principal type 'group')."""
    position = 0
    if page is not None and page > 0:
        position = (page - 1) * limit

    result = _get_client().query_and_get(
        object_type="x:Account",
        filter={"type": ["group"]},
        limit=limit,
        position=position,
        properties=["id", "name", "type", "description"],
    )
    return {
        "items": result.get("items", []),
        "total": result.get("total", 0),
        "page": page or 1,
        "limit": limit,
    }


@_op(stalwart_read)
def list_mailing_lists(
    page: int | None = None,
    limit: int = 20,
):
    """List mailing lists."""
    position = 0
    if page is not None and page > 0:
        position = (page - 1) * limit

    result = _get_client().query_and_get(
        object_type="x:MailingList",
        limit=limit,
        position=position,
        properties=["id", "name", "description"],
    )
    return {
        "items": result.get("items", []),
        "total": result.get("total", 0),
        "page": page or 1,
        "limit": limit,
    }


# ── stalwart_write ────────────────────────────────────────────────────

@_op(stalwart_write)
def create_principal(
    type: str,
    name: str,
    description: str | None = None,
    quota: int | None = None,
    secrets: list | None = None,
    emails: list | None = None,
    urls: list | None = None,
    memberOf: list | None = None,
    roles: list | None = None,
    lists: list | None = None,
    members: list | None = None,
    enabledPermissions: list | None = None,
    disabledPermissions: list | None = None,
    externalMembers: list | None = None,
):
    """Create a principal (account). type: individual, group, list, domain, tenant, role, apiKey, oauthClient."""
    props: dict = {"type": type, "name": name}
    if description is not None:
        props["description"] = description
    if quota is not None:
        props["quota"] = quota
    if secrets is not None:
        props["secrets"] = secrets
    if emails is not None:
        props["emails"] = emails
    if urls is not None:
        props["urls"] = urls
    if memberOf is not None:
        props["memberOf"] = memberOf
    if roles is not None:
        props["roles"] = roles
    if lists is not None:
        props["lists"] = lists
    if members is not None:
        props["members"] = members
    if enabledPermissions is not None:
        props["enabledPermissions"] = enabledPermissions
    if disabledPermissions is not None:
        props["disabledPermissions"] = disabledPermissions
    if externalMembers is not None:
        props["externalMembers"] = externalMembers

    result = _get_client().set_objects(
        object_type="x:Account",
        create={"newPrincipal": props},
    )
    created = result.get("created", {})
    if created:
        return {"status": "created", "principal": list(created.values())[0]}
    not_created = result.get("notCreated", {})
    if not_created:
        return {"status": "error", "not_created": not_created}
    return _ok(result)


@_op(stalwart_write)
def update_principal(id: str, changes: list):
    """Update a principal. changes: array of {path, value} for JMAP patch.

    Each change: {"path": "/propertyName", "value": newValue}
    Example: {"path": "/description", "value": "New description"}
    """
    # Convert changes array to a flat update dict
    update_props = {}
    for change in changes:
        if isinstance(change, dict):
            path = change.get("path", "").lstrip("/")
            value = change.get("value")
            if path:
                update_props[path] = value

    if not update_props:
        return {"error": "No valid changes provided. Use [{path: '/field', value: newValue}] format."}

    result = _get_client().set_objects(
        object_type="x:Account",
        update={id: update_props},
    )
    updated = result.get("updated", {})
    if updated:
        return {"status": "updated", "principal": updated.get(id, {})}
    not_updated = result.get("notUpdated", {})
    if not_updated:
        return {"status": "error", "not_updated": not_updated}
    return _ok(result)


@_op(stalwart_write)
def start_queue():
    """Resume mail queue processing."""
    return _unavailable(
        "StartQueue",
        "Queue start/stop has no JMAP management method in Stalwart v0.16. "
        "Use the WebAdmin Management > Emails section.",
    )


@_op(stalwart_write)
def stop_queue():
    """Pause mail queue processing."""
    return _unavailable(
        "StopQueue",
        "Queue start/stop has no JMAP management method in Stalwart v0.16. "
        "Use the WebAdmin Management > Emails section.",
    )


@_op(stalwart_write)
def reschedule_messages(filter: str | None = None):
    """Bulk reschedule queued messages. filter: query string.

    Reschedules matching messages to retry immediately by updating nextRetry."""
    props = {"nextRetry": "now"}
    if filter is not None:
        # Filter is applied via JMAP query, but /set needs explicit IDs
        # For now, this requires the caller to use list_queue_messages first
        # and pass specific IDs to reschedule_message
        return {
            "error": "Bulk reschedule requires explicit message IDs.",
            "suggestion": "Use ListQueueMessages to find message IDs, "
                          "then RescheduleMessage for each.",
        }

    return _unavailable("RescheduleMessages",
                        "Bulk reschedule requires explicit IDs. "
                        "Use RescheduleMessage for individual messages.")


@_op(stalwart_write)
def reschedule_message(id: str):
    """Reschedule a single queued message by ID (sets nextRetry to now)."""
    result = _get_client().set_objects(
        object_type="x:QueuedMessage",
        update={id: {"nextRetry": "now"}},
    )
    updated = result.get("updated", {})
    if updated:
        return {"status": "rescheduled", "id": id}
    not_updated = result.get("notUpdated", {})
    if not_updated:
        return {"status": "error", "not_updated": not_updated, "id": id}
    return _ok(result)


@_op(stalwart_write)
def update_settings(settings: list):
    """Update system settings. settings: array of {key, value} pairs.

    Each item: {"key": "propertyName", "value": newValue}
    Example: {"key": "defaultHostname", "value": "mail.example.com"}
    """
    update_props = {}
    for s in settings:
        if isinstance(s, dict):
            key = s.get("key", "")
            value = s.get("value")
            if key and key != "id":
                update_props[key] = value

    if not update_props:
        return {"error": "No valid settings provided."}

    result = _get_client().set_objects(
        object_type="x:SystemSettings",
        update={"singleton": update_props},
    )
    updated = result.get("updated", {})
    if updated:
        return {"status": "updated", "settings": updated.get("singleton", {})}
    return _ok(result)


@_op(stalwart_write)
def generate_dkim(
    domain: str,
    selector: str,
    algorithm: str = "rsa-sha256",
):
    """Generate DKIM keys. Returns the new DKIM signature info.

    algorithm: rsa-sha256 or ed25519-sha256
    """
    result = _get_client().set_objects(
        object_type="x:DkimSignature",
        create={
            "newDkim": {
                "domain": domain,
                "selector": selector,
                "algorithm": algorithm,
            }
        },
    )
    created = result.get("created", {})
    if created:
        sig = list(created.values())[0]
        return {"status": "created", "dkim": sig}
    not_created = result.get("notCreated", {})
    if not_created:
        return {"status": "error", "not_created": not_created}
    return _ok(result)


@_op(stalwart_write)
def train_spam(message: str):
    """Train global spam classifier with a spam message."""
    return _unavailable(
        "TrainSpam",
        "Spam filter training has no JMAP management endpoint in Stalwart v0.16. "
        "Use the WebAdmin or IMAP Junk folder for bayes training.",
    )


@_op(stalwart_write)
def train_ham(message: str):
    """Train global spam classifier with a ham (not spam) message."""
    return _unavailable(
        "TrainHam",
        "Spam filter training has no JMAP management endpoint in Stalwart v0.16. "
        "Use the WebAdmin or IMAP Junk folder for bayes training.",
    )


@_op(stalwart_write)
def train_account_spam(account_id: str, message: str):
    """Train per-account spam classifier with a spam message."""
    return _unavailable(
        "TrainAccountSpam",
        "Per-account spam filter training has no JMAP management endpoint.",
    )


@_op(stalwart_write)
def train_account_ham(account_id: str, message: str):
    """Train per-account spam classifier with a ham (not spam) message."""
    return _unavailable(
        "TrainAccountHam",
        "Per-account spam filter training has no JMAP management endpoint.",
    )


@_op(stalwart_write)
def classify_spam(
    message: str,
    remote_ip: str | None = None,
    ehlo_domain: str | None = None,
    authenticated_as: str | None = None,
    is_tls: bool | None = None,
    env_from: str | None = None,
    env_from_flags: str | None = None,
    env_rcpt_to: list | None = None,
):
    """Test spam classification for a message."""
    return _unavailable(
        "ClassifySpam",
        "Spam classification testing has no JMAP endpoint in Stalwart v0.16. "
        "Use the WebAdmin or send a test message.",
    )


@_op(stalwart_write)
def restore_deleted_messages(account_id: str, messages: list):
    """Restore deleted messages. messages: array of message IDs."""
    return _unavailable(
        "RestoreDeletedMessages",
        "Message restore has no JMAP management endpoint. Use IMAP or the WebAdmin.",
    )


@_op(stalwart_write)
def update_encryption(
    type: str | None = None,
    algo: str | None = None,
    certs: str | None = None,
):
    """Update encryption-at-rest settings."""
    return _unavailable(
        "UpdateEncryption",
        "Encryption settings are managed via x:SystemSettings JMAP object. "
        "Use UpdateSettings with appropriate encryption keys.",
    )


@_op(stalwart_write)
def update_auth(
    type: str | None = None,
    totp_token: str | None = None,
    app_passwords: list | None = None,
):
    """Update authentication settings (2FA, app passwords)."""
    return _unavailable(
        "UpdateAuth",
        "Authentication settings are managed via x:SystemSettings JMAP object. "
        "Use UpdateSettings with appropriate authentication keys.",
    )


# ── stalwart_delete ───────────────────────────────────────────────────

@_op(stalwart_delete)
def delete_principal(id: str):
    """Delete a principal. Irreversible."""
    result = _get_client().set_objects(
        object_type="x:Account",
        destroy=[id],
    )
    destroyed = result.get("destroyed", [])
    if destroyed:
        return {"status": "deleted", "id": destroyed[0]}
    not_destroyed = result.get("notDestroyed", {})
    if not_destroyed:
        return {"status": "error", "not_destroyed": not_destroyed}
    return _ok(result)


@_op(stalwart_delete)
def delete_queue_messages(text: str | None = None):
    """Bulk delete queued messages by filter text.

    WARNING: This queries matching messages then deletes them all.
    """
    # First query to find matching IDs
    filter_dict = None
    if text is not None:
        filter_dict = {"text": text}

    result = _get_client().query_and_get(
        object_type="x:QueuedMessage",
        filter=filter_dict,
        limit=250,
        properties=["id"],
    )
    ids = [item["id"] for item in result.get("items", []) if "id" in item]

    if not ids:
        return {"status": "ok", "deleted": 0, "message": "No matching messages found."}

    delete_result = _get_client().set_objects(
        object_type="x:QueuedMessage",
        destroy=ids,
    )
    destroyed = delete_result.get("destroyed", [])
    return {
        "status": "deleted",
        "deleted_count": len(destroyed),
        "ids": destroyed,
    }


@_op(stalwart_delete)
def delete_queue_message(id: str):
    """Delete a single queued message by ID."""
    result = _get_client().set_objects(
        object_type="x:QueuedMessage",
        destroy=[id],
    )
    destroyed = result.get("destroyed", [])
    if destroyed:
        return {"status": "deleted", "id": destroyed[0]}
    not_destroyed = result.get("notDestroyed", {})
    if not_destroyed:
        return {"status": "error", "not_destroyed": not_destroyed}
    return _ok(result)


@_op(stalwart_delete)
def purge_blobs():
    """Purge unreferenced blobs from store."""
    return _unavailable(
        "PurgeBlobs",
        "Store purge operations have no JMAP management endpoint. "
        "Use the WebAdmin Actions section.",
    )


@_op(stalwart_delete)
def purge_data():
    """Purge data store."""
    return _unavailable(
        "PurgeData",
        "Store purge operations have no JMAP management endpoint.",
    )


@_op(stalwart_delete)
def purge_cache():
    """Purge in-memory cache."""
    return _unavailable(
        "PurgeCache",
        "Store purge operations have no JMAP management endpoint.",
    )


@_op(stalwart_delete)
def purge_all_accounts():
    """Purge all account data."""
    return _unavailable(
        "PurgeAllAccounts",
        "Store purge operations have no JMAP management endpoint.",
    )


@_op(stalwart_delete)
def purge_account(account_id: str):
    """Purge a single account's data."""
    return _unavailable(
        "PurgeAccount",
        "Store purge operations have no JMAP management endpoint.",
    )


@_op(stalwart_delete)
def delete_global_bayes():
    """Delete global Bayes spam model."""
    return _unavailable(
        "DeleteGlobalBayes",
        "Bayes model management has no JMAP endpoint.",
    )


@_op(stalwart_delete)
def delete_account_bayes(account_id: str):
    """Delete per-account Bayes spam model."""
    return _unavailable(
        "DeleteAccountBayes",
        "Bayes model management has no JMAP endpoint.",
    )


@_op(stalwart_delete)
def reset_imap_uids(account_id: str):
    """Reset IMAP UIDs for an account."""
    return _unavailable(
        "ResetImapUids",
        "IMAP UID reset has no JMAP management endpoint.",
    )


# ── stalwart_admin ────────────────────────────────────────────────────

@_op(stalwart_admin)
def reload_config(dry_run: bool = False):
    """Reload server configuration. Returns warnings and errors.

    Note: Stalwart Community Edition does not expose a JMAP reload endpoint.
    This operation checks connectivity and reports current state.
    """
    try:
        client = _get_client()
        result = client.query_and_get(
            object_type="x:Account",
            limit=1,
            properties=["id"],
        )
        status = {
            "status": "ok",
            "note": "Stalwart Community Edition loads config from database on restart. "
                    "No live reload needed for most changes — they take effect immediately "
                    "via the JMAP management API.",
        }
        if dry_run:
            status["dry_run"] = True
            status["config_source"] = "RocksDB internal database"
        return status
    except Exception as exc:
        return {"status": "error", "detail": str(exc)}


@_op(stalwart_admin)
def update_spam_filter():
    """Update spam filter databases."""
    return _unavailable(
        "UpdateSpamFilter",
        "Spam filter update has no JMAP management endpoint.",
    )


@_op(stalwart_admin)
def update_webadmin():
    """Update web admin UI (no-op: Stalwart container image bundles WebAdmin)."""
    return {
        "status": "ok",
        "note": "WebAdmin is bundled in the Stalwart container image. "
                "Update the Docker image to update the WebAdmin.",
    }


@_op(stalwart_admin)
def reindex():
    """Rebuild full-text search index."""
    return _unavailable(
        "Reindex",
        "Full-text reindex has no JMAP management endpoint. "
        "Use the WebAdmin Actions section.",
    )


@_op(stalwart_admin)
def get_diagnostics_token():
    """Get diagnostics/troubleshooting token."""
    return _unavailable(
        "GetDiagnosticsToken",
        "Diagnostics token is available via /api/token/ endpoint, not JMAP. "
        "Use the WebAdmin for troubleshooting.",
    )


@_op(stalwart_admin)
def validate_dmarc(
    remote_ip: str,
    ehlo_domain: str,
    mail_from: str,
    body: str,
):
    """Validate DMARC for a message. Returns SPF, DKIM, ARC, DMARC results."""
    return _unavailable(
        "ValidateDmarc",
        "DMARC validation has no JMAP management endpoint.",
    )


@_op(stalwart_admin)
def get_metrics_token():
    """Get token for live metrics streaming."""
    return _unavailable(
        "GetMetricsToken",
        "Metrics token has no JMAP management endpoint.",
    )


@_op(stalwart_admin)
def get_tracing_token():
    """Get token for live trace streaming."""
    return _unavailable(
        "GetTracingToken",
        "Tracing token has no JMAP management endpoint.",
    )


@_op(stalwart_admin)
def get_encryption_settings():
    """Get encryption-at-rest settings."""
    return _unavailable(
        "GetEncryptionSettings",
        "Encryption settings are available via x:SystemSettings JMAP object. "
        "Use GetSettingsByGroup or ListSettings.",
    )


@_op(stalwart_admin)
def get_auth_settings():
    """Get authentication settings (2FA, app passwords)."""
    return _unavailable(
        "GetAuthSettings",
        "Authentication settings are available via x:SystemSettings JMAP object. "
        "Use GetSettingsByGroup or ListSettings.",
    )

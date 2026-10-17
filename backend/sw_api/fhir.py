"""Read-only FHIR R4 projection of existing verdicts, alerts, and monitor state.

Local terminology/extension URLs are identifiers, not hosted conformance resources.
No patient records, demographics, staff recipients, or raw event payloads are serialized.
"""
from __future__ import annotations

import copy
from datetime import datetime, timezone
from html import unescape
import re
from uuid import NAMESPACE_URL, uuid5

BASE = "https://sentinelward.local/fhir"
VERDICT_SYSTEM = BASE + "/CodeSystem/verdict"
CHECK_SYSTEM = BASE + "/CodeSystem/check"
ALERT_STATE = BASE + "/StructureDefinition/alert-state"
ALERT_VERDICTS = {"EMERGENCY", "TAMPERING", "BOTH", "DEVICE_ATTACK"}
LOCAL_STATES = {"open": "open", "escalated": "open", "acked": "acknowledged", "closed": "resolved"}

# Predecessors establish transitions and retain historical context for alert updates.
# Read via PostgresStore's existing serialized async reader; never flush/write the batch queue.
VERDICT_SQL = """
WITH scoped AS (
    SELECT bed_id, ts, verdict, msg FROM verdicts
    WHERE ts > %s AND ts <= %s AND (%s::text IS NULL OR bed_id = %s)
), prior AS (
    SELECT msg, row_number() OVER (PARTITION BY bed_id, verdict ORDER BY ts DESC) AS rn
    FROM scoped WHERE ts < %s
)
SELECT msg FROM scoped WHERE ts >= %s
UNION ALL SELECT msg FROM prior WHERE rn = 1
"""
ALERT_SQL = """SELECT msg FROM alerts WHERE ts >= %s AND ts <= %s AND ts > %s
AND (%s::text IS NULL OR bed_id = %s)"""


def iso(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def uid(key: str) -> str:
    return str(uuid5(NAMESPACE_URL, BASE + "/" + key))


def url(key: str) -> str:
    return "urn:uuid:" + uid(key)


def concept(system: str, code: str, text: str | None = None) -> dict:
    result = {"coding": [{"system": system, "code": code}]}
    if text:
        result["text"] = text
    return result


def plain(text: str, identifiers: list[str]) -> str:
    """Remove configured patient identifiers from otherwise plain source explanations."""
    text = " ".join(re.sub(r"<[^>]*>", "", unescape(text)).split())
    for identifier in sorted(set(identifiers), key=len, reverse=True):
        identifier = " ".join(unescape(identifier).split())
        if identifier:
            text = re.sub(re.escape(identifier), "[redacted]", text, flags=re.IGNORECASE)
    return " ".join(text.split()) or "No reason supplied by source."


async def export_bundle(runtime, since: int = 0, bed: str | None = None) -> dict:
    """Inclusive source-time window [since, read time], plus observations needed by alerts.

    PostgreSQL is authoritative for history; recent RAM verdicts include unflushed messages.
    Capture RAM before awaiting SQL. The route rejects a concurrent demo reset.
    """
    state, store = runtime.state, runtime.store
    now = runtime.clock.ms()
    reset_at = runtime.ingest.reset_at if runtime.ingest.reset_at is not None else -1
    beds = {key: value for key, value in state.beds.items() if bed is None or key == bed}
    identifiers = [b.cfg.initials for b in state.beds.values()]
    devices = [(b.cfg.device_id, state.devices[b.cfg.device_id].isolated_since() is not None) for b in beds.values()]
    live_verdicts = [m for b in beds.values() for m in reversed(b.recent_verdicts)] + list(store.verdicts.values())
    if store.durable:
        from .postgres import SQL_VERDICT
        # PostgresStore retains all uncommitted operations until a successful commit,
        # including out-of-order verdicts that WardState's short buffer does not retain.
        # This adapter reads the existing queue; it never flushes or changes it.
        live_verdicts += [params[-1].obj for sql, params in store.writer._queue if sql == SQL_VERDICT]
    live_verdicts = copy.deepcopy(live_verdicts)
    live_alerts = copy.deepcopy(list(store.alerts.values()) + list(state.alerts.values()))
    stored_verdicts, stored_alerts = [], []
    if store.durable:
        stored_verdicts = [r["msg"] for r in await store._query(
            VERDICT_SQL, (reset_at, now, bed, bed, since, since))]
        stored_alerts = [r["msg"] for r in await store._query(
            ALERT_SQL, (since, now, reset_at, bed, bed))]
    verdicts = {(m["bed_id"], m["ts"]): m for m in stored_verdicts + live_verdicts
                if m["bed_id"] in beds and reset_at < m["ts"] <= now}
    alerts = {}
    for m in stored_alerts + live_alerts:
        if m["bed_id"] in beds and reset_at < m["ts"] <= now:
            old = alerts.get(m["alert_id"])
            if old is None or m["ts"] >= old["ts"]:
                alerts[m["alert_id"]] = m

    entries = {}

    def add(key: str, resource: dict) -> str:
        ref = url(key)
        resource["id"] = uid(key)
        entries[ref] = {"fullUrl": ref, "resource": resource}
        return ref

    for device, isolated in devices:
        add("device/" + device, {"resourceType": "Device", "status": "inactive" if isolated else "active",
                                "identifier": [{"system": BASE + "/NamingSystem/monitor", "value": device}]})

    def observation(message: dict, key: str, derived: bool = False) -> str:
        bed_id = message["bed_id"]
        components = []
        for model in (f"M{i}" for i in range(1, 7)):
            comp = {"code": concept(CHECK_SYSTEM, model)}
            value = message.get("scores", {}).get(model)
            if value is None:
                comp["dataAbsentReason"] = concept("http://terminology.hl7.org/CodeSystem/data-absent-reason", "unknown")
            else:
                comp["valueQuantity"] = {"value": value, "unit": "1", "system": "http://unitsofmeasure.org", "code": "1"}
            components.append(comp)
        reason = message.get("text", "") if derived else "; ".join(message.get("reasons", []))
        if derived:
            reason = "Alert-derived verdict; check scores unavailable. " + reason
        return add(key, {
            "resourceType": "Observation", "status": "preliminary" if derived else "final",
            "code": concept(BASE + "/CodeSystem/observation", "verdict", "SentinelWard verdict"),
            "subject": {"identifier": {"system": BASE + "/NamingSystem/bed", "value": bed_id}},
            "effectiveDateTime": iso(message["ts"]),
            "device": {"reference": url("device/" + beds[bed_id].cfg.device_id)},
            "valueCodeableConcept": concept(VERDICT_SYSTEM, message["verdict"]),
            "component": components, "note": [{"text": plain(reason, identifiers)}],
        })

    ordered = sorted(verdicts.values(), key=lambda m: (m["bed_id"], m["ts"]))
    previous = {}
    for m in ordered:
        changed = previous.get(m["bed_id"]) != m["verdict"]
        previous[m["bed_id"]] = m["verdict"]
        if m["ts"] >= since and changed:
            observation(m, f"verdict/{m['bed_id']}/{m['ts']}")

    for a in sorted(alerts.values(), key=lambda m: (m["ts"], m["alert_id"])):
        if a["ts"] < since or a["verdict"] not in ALERT_VERDICTS:
            continue
        matches = [m for m in ordered if m["bed_id"] == a["bed_id"] and m["verdict"] == a["verdict"] and m["ts"] <= a["ts"]]
        if matches:
            m = matches[-1]
            implicated = observation(m, f"verdict/{m['bed_id']}/{m['ts']}")
        else:
            implicated = observation(a, "alert-observation/" + a["alert_id"], derived=True)
        lifecycle = LOCAL_STATES[a["status"]]
        add("alert/" + a["alert_id"], {
            "resourceType": "DetectedIssue", "status": "final" if lifecycle == "resolved" else "preliminary",
            "code": concept(VERDICT_SYSTEM, a["verdict"]),
            "severity": "high" if a["priority"] == "high" else "moderate",
            "identifiedDateTime": iso(a["ts"]), "detail": plain(a["text"], identifiers),
            "implicated": [{"reference": implicated}], "extension": [{"url": ALERT_STATE, "valueCode": lifecycle}],
        })

    return {"resourceType": "Bundle", "type": "collection", "timestamp": iso(now),
            "meta": {"security": [{"system": BASE + "/CodeSystem/security", "code": "pseudonymous",
                                    "display": "Bed identifiers only; patient names and demographics excluded"}]},
            "entry": list(entries.values())}


def capability_statement(now: int) -> dict:
    """Advertise the two pull endpoints without claiming a general FHIR REST server."""
    return {
        "resourceType": "CapabilityStatement", "status": "active", "date": iso(now), "kind": "instance",
        "fhirVersion": "4.0.1", "format": ["json"],
        "implementation": {"description": "SentinelWard read-only interoperability export"},
        "description": "Authenticated GET /api/fhir/Bundle?since=<epoch ms>&bed=<B01..B12>; GET /api/fhir/metadata. "
                       "Collection export only; no individual resource endpoints, writes, or push subscriptions.",
        "rest": [{"mode": "server", "documentation": "Same sessions and read roles as /api/ward. Local terminology.",
                  "resource": [{"type": kind, "documentation": "Embedded in GET /api/fhir/Bundle only."}
                               for kind in ("Bundle", "Observation", "DetectedIssue", "Device")]}],
    }

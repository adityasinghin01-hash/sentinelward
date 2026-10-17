"""Strict, offline checks for the R4 subset emitted here, not a full FHIR validator.

Required fields/cardinality follow hl7.org/fhir/R4/{bundle,observation,detectedissue,device}.html.
Unknown fields are rejected so non-R4 status codes or accidental patient data cannot hide.
"""
from datetime import datetime
import math
import re
from uuid import UUID

STATUSES = {"registered", "preliminary", "final", "amended", "corrected", "cancelled", "entered-in-error", "unknown"}
VERDICTS = {"NORMAL", "EMERGENCY", "TAMPERING", "BOTH", "DEVICE_ATTACK", "DRIFTING", "LOOSE_SENSOR", "UNSURE"}


def fields(obj, required, optional=()):
    assert isinstance(obj, dict)
    assert set(required) <= obj.keys()
    assert obj.keys() <= set(required) | set(optional)


def nonempty(value):
    assert isinstance(value, list) and value
    return value


def instant(value):
    assert isinstance(value, str) and value.endswith("Z")
    assert datetime.fromisoformat(value.replace("Z", "+00:00")).tzinfo


def coding(value):
    fields(value, ("system", "code"), ("display",))
    assert value["system"].startswith(("http://", "https://"))
    assert isinstance(value["code"], str) and value["code"]


def concept(value):
    fields(value, ("coding",), ("text",))
    for c in nonempty(value["coding"]):
        coding(c)


def reference(value, targets=None):
    fields(value, ("reference",))
    assert value["reference"].startswith("urn:uuid:")
    UUID(value["reference"][9:])
    if targets is not None:
        assert value["reference"] in targets


def validate_bundle(bundle):
    fields(bundle, ("resourceType", "type", "timestamp", "meta"), ("entry",))
    assert bundle["resourceType"] == "Bundle" and bundle["type"] == "collection"
    instant(bundle["timestamp"])
    fields(bundle["meta"], ("security",))
    for label in nonempty(bundle["meta"]["security"]):
        coding(label)
    entries = bundle.get("entry", [])
    if "entry" in bundle:
        nonempty(entries)
    targets = {}
    for entry in entries:
        fields(entry, ("fullUrl", "resource"))
        reference({"reference": entry["fullUrl"]})
        assert entry["fullUrl"] not in targets
        targets[entry["fullUrl"]] = entry["resource"]
    for resource in targets.values():
        kind = resource["resourceType"]
        assert re.fullmatch(r"[A-Za-z0-9\-.]{1,64}", resource["id"])
        if kind == "Device":
            fields(resource, ("resourceType", "id", "identifier", "status"))
            assert resource["status"] in {"active", "inactive", "entered-in-error", "unknown"}
            assert len(nonempty(resource["identifier"])) == 1
            fields(resource["identifier"][0], ("system", "value"))
            assert re.fullmatch(r"MON-(0[1-9]|1[0-2])", resource["identifier"][0]["value"])
        elif kind == "Observation":
            fields(resource, ("resourceType", "id", "status", "code", "subject", "effectiveDateTime",
                              "device", "valueCodeableConcept", "component", "note"))
            assert resource["status"] in STATUSES
            concept(resource["code"])
            concept(resource["valueCodeableConcept"])
            assert resource["valueCodeableConcept"]["coding"][0]["code"] in VERDICTS
            fields(resource["subject"], ("identifier",))
            fields(resource["subject"]["identifier"], ("system", "value"))
            assert re.fullmatch(r"B(0[1-9]|1[0-2])", resource["subject"]["identifier"]["value"])
            instant(resource["effectiveDateTime"])
            reference(resource["device"], targets)
            assert targets[resource["device"]["reference"]]["resourceType"] == "Device"
            for note in nonempty(resource["note"]):
                fields(note, ("text",))
                assert isinstance(note["text"], str) and note["text"]
            assert len(nonempty(resource["component"])) == 6
            models = []
            for comp in resource["component"]:
                fields(comp, ("code",), ("valueQuantity", "dataAbsentReason"))
                concept(comp["code"])
                models.append(comp["code"]["coding"][0]["code"])
                assert ("valueQuantity" in comp) != ("dataAbsentReason" in comp)
                if "valueQuantity" in comp:
                    q = comp["valueQuantity"]
                    fields(q, ("value", "system", "code", "unit"))
                    assert type(q["value"]) in (int, float) and math.isfinite(q["value"])
                    assert 0 <= q["value"] <= 1 and q["code"] == "1"
                    assert q["system"] == "http://unitsofmeasure.org"
                else:
                    concept(comp["dataAbsentReason"])
            assert models == [f"M{i}" for i in range(1, 7)]
        elif kind == "DetectedIssue":
            fields(resource, ("resourceType", "id", "status", "severity", "code", "detail", "implicated",
                              "identifiedDateTime", "extension"))
            assert resource["status"] in STATUSES
            assert resource["severity"] in {"high", "moderate", "low"}
            concept(resource["code"])
            assert isinstance(resource["detail"], str) and resource["detail"]
            instant(resource["identifiedDateTime"])
            assert len(nonempty(resource["implicated"])) == 1
            for ref in resource["implicated"]:
                reference(ref, targets)
                assert targets[ref["reference"]]["resourceType"] == "Observation"
            assert len(nonempty(resource["extension"])) == 1
            ext = resource["extension"][0]
            fields(ext, ("url", "valueCode"))
            assert ext["url"].endswith("/StructureDefinition/alert-state")
            assert ext["valueCode"] in {"open", "acknowledged", "resolved"}
        else:
            raise AssertionError(f"Unsupported resource: {kind}")

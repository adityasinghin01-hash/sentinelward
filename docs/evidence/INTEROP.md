# SentinelWard → HL7 FHIR R4

Authenticated read-only output for an EHR adapter or central-station consumer:
`GET /api/fhir/Bundle?since=<UTC epoch ms>&bed=B03` and `GET /api/fhir/metadata`.
Both reuse the existing read-session rules. Output is `application/fhir+json`.
The Bundle is a **collection**, not a transaction or a search response.

| Existing SentinelWard evidence | FHIR R4 representation |
| --- | --- |
| Verdict transition per bed | `Observation.status=final`, local code “SentinelWard verdict” |
| NORMAL / EMERGENCY / TAMPERING / BOTH / DEVICE_ATTACK / DRIFTING / LOOSE_SENSOR / UNSURE | `valueCodeableConcept` using `https://sentinelward.local/fhir/CodeSystem/verdict` |
| Source verdict `ts`, configured monitor | UTC `effectiveDateTime`, `device` reference to MON-xx Device |
| Verdict's own M1–M6 scores | Six components, local check codes, dimensionless UCUM quantities 0–1; unknown scores use `dataAbsentReason` |
| Verdict reasons / alert text | Plain `Observation.note` / `DetectedIssue.detail`; configured patient identifiers redacted |
| EMERGENCY / TAMPERING / BOTH / DEVICE_ATTACK alert | `DetectedIssue` implicating the corresponding Observation |
| Alert priority high / other | `DetectedIssue.severity` high / moderate; DEVICE_ATTACK retains existing non-high priority |
| open or escalated / acked / closed | Local `alert-state` extension open / acknowledged / resolved; standard R4 status preliminary / preliminary / final |
| Configured monitor, isolation in force | `Device.identifier=MON-xx`, current status active / inactive when cut off |
| Bed ID only | `Observation.subject.identifier`; Bundle `meta.security` label says pseudonymous |

`DetectedIssue.status` uses the required R4 ObservationStatus vocabulary, which has no literal
open/acknowledged/resolved codes. The extension preserves workflow meaning without inserting
invalid standard codes. Local extension: `https://sentinelward.local/fhir/StructureDefinition/alert-state`.
See the official [DetectedIssue R4 definition](https://hl7.org/fhir/R4/detectedissue.html),
[Observation](https://hl7.org/fhir/R4/observation.html), [Device](https://hl7.org/fhir/R4/device.html),
[Bundle](https://hl7.org/fhir/R4/bundle.html), and
[CapabilityStatement](https://hl7.org/fhir/R4/capabilitystatement.html).

`since` defaults to 0 and includes timestamps equal to the boundary, through the read time.
Consecutive equal verdict codes are collapsed, including comparison with the previous verdict
before the boundary. Alerts use their **latest state update timestamp**, including acknowledged
and resolved updates; old open alerts outside the window are not repeated. Supporting Observations
can precede `since` to keep references meaningful. Without a retained matching verdict, an alert
produces an explicitly labelled alert-derived Observation with unknown scores. Devices represent
current state and remain present for selected beds even with no clinical events. Consumers should
upsert using stable resource IDs and overlap polling windows to allow delayed messages.

The exporter uses actual accepted backend messages: memory-store data in demo mode, persisted
PostgreSQL verdicts/alerts plus live state and uncommitted verdicts in the writer queue in database mode.
The adapter reuses the existing serialized PostgreSQL reader and snapshots its writer queue
without flushing it; this read-only adapter depends on those existing store interfaces. It never changes upstream verdicts,
decisions, alerts, device isolation, MQTT messages, or agent/brain behavior.

The [sample Bundle](raw/fhir-sample-bundle.json) is generated through the real ASGI endpoint from
`backend/tests/test_fhir.py::sample_fixture`, using normal message builders and ingest. It represents
B01 EMERGENCY open, B03 TAMPERING acknowledged with MON-03 cut off, and B05 BOTH resolved;
it contains 3 Observations, 3 DetectedIssues, and 12 Devices. It is synthetic fixture evidence,
not a captured hospital export. The test compares the saved JSON exactly with the generated output.

Validation is offline, dependency-free hand checking in `backend/tests/fhir_validator.py`: required
fields, singleton/list cardinality, allowed status/verdict codes, six score ranges/unknowns, timezone,
UUID uniqueness and reference closure. Negative tests demonstrate rejection of missing fields,
invalid status/score/cardinality/reference and accidental extra fields. This checks our emitted R4
subset; it is **not** the official HL7 validator or certification. The endpoint tests cover an empty
ward, all eight verdicts, cutoff, alert lifecycle, filters, all read roles, expiry, no side effects,
and pseudonymous output. SQL-fixture tests exercise persisted history and failure/reset handling;
they do not replace running the optional PostgreSQL integration suite against a live database.

Limits: not certified, no tested hospital-EHR connection, no standard LOINC/SNOMED mapping,
local CodeSystem/extension URLs are not hosted conformance definitions, no HL7 v2 feed,
**read-only pull, not push**, no subscriptions, pagination, individual resource endpoints, or patient
identity linkage. Bed IDs are pseudonyms, not durable patient identities across admissions. Names,
initials and demographics are excluded from structured output; configured identifiers are scrubbed
from explanations, but this is not a general free-text de-identification service. Alert evidence is linked by bed, verdict code, and the latest matching source timestamp; upstream
messages have no explicit verdict-to-alert event link. Latest alert state
is exported, not every escalation/ack event; device status is current, not historical connectivity.
Memory-mode history lasts until reset/process exit. PostgreSQL history is limited by stored data and
both modes honor the demo reset boundary. Use bounded windows for larger datasets.

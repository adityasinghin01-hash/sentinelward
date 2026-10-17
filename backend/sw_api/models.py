"""HTTP contracts; MQTT messages remain sw_common dictionaries."""
from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator

from .chip import ChipOpinion

FrontendRole = Literal["nurse", "doctor", "it", "biomedical", "operator"]
Verdict = Literal["NORMAL", "EMERGENCY", "BOTH", "TAMPERING", "UNSURE", "DRIFTING", "LOOSE_SENSOR", "DEVICE_ATTACK"]


class Input(BaseModel):
    model_config = ConfigDict(strict=True, extra="ignore")


class SessionInput(Input):
    role: Literal["nurse", "doctor", "it", "biomedical", "operator", "biomed", "admin"] | None = None
    username: str | None = None
    pin: str | None = None

    @model_validator(mode="after")
    def credentials(self):
        if self.username is not None or self.pin is not None:
            if self.username is None or self.pin is None or self.role is not None:
                raise ValueError("supply username and pin together, or role")
        elif self.role is None:
            raise ValueError("supply username and pin, or role")
        return self


class SessionResponse(BaseModel):
    token: str
    role: FrontendRole
    name: str
    display_name: str


class BedCommand(Input):
    bedId: str | None = None
    notes: str = Field(default="", max_length=4000)


class Acknowledge(BedCommand):
    type: Literal["acknowledge_alert"] | None = None


class Bedside(BedCommand):
    type: Literal["confirm_bedside"] | None = None
    status: Literal["patient_ok", "patient_not_ok"] | None = None
    result: Literal["patient_ok", "patient_not_ok"] | None = None

    @model_validator(mode="after")
    def bedside_result(self):
        if self.status is None and self.result is None:
            raise ValueError("status or result is required")
        if self.status is not None and self.result is not None and self.status != self.result:
            raise ValueError("status and result disagree")
        return self


class Escalate(BedCommand):
    type: Literal["escalate_alert"] | None = None
    alertId: str | None = None


class Isolate(BedCommand):
    type: Literal["isolate_device"] | None = None
    deviceId: str | None = None


class Undo(BedCommand):
    type: Literal["undo_action"] | None = None
    originalActionId: str | None = None


class DemoRun(Input):
    scenario: Literal["full_ward_script", "emergency", "loose_sensor", "drifting", "replay_attack", "fake_flatline", "flood"] = "full_ward_script"
    speed: Literal[1, 2, 5] = 1
    start_at_s: int = Field(default=0, ge=0, lt=1200)


class Receipt(BaseModel):
    command_id: str
    accepted_at: int
    request_id: str | None = None


class DemoReceipt(Receipt):
    accepted: bool = True
    run_id: str


class Vitals(BaseModel):
    hr: float | None
    spo2: float | None
    systolic: float | None
    diastolic: float | None


class Waveform(BaseModel):
    ecg: list[float]
    ppg: list[float]


class Patient(BaseModel):
    initials: str
    age: int | None
    sex: str | None


class TrustedSnapshot(BaseModel):
    captured_at: int
    vitals: Vitals
    waveform: Waveform


class RawBed(BaseModel):
    chip_opinion: ChipOpinion | None = None
    bed_id: str
    device_id: str
    patient: Patient | None = None
    verdict: Verdict | None
    priority: Literal["none", "low", "medium", "high"]
    trust_score: float = Field(ge=0, le=100)
    is_trusted: bool
    connected: bool
    isolated: bool
    reason: str
    requested_action: str
    acknowledged: bool
    last_updated_at: int | None
    vitals: Vitals | None
    waveform: Waveform
    last_trusted: TrustedSnapshot | None
    display: Literal["live", "last_trusted", "offline", "empty"]
    offline_since: int | None
    manual: dict[str, Any] | None = None
    last_bedside_check: dict[str, Any] | None = None
    assignment: dict[str, Any] | None = None
    nurse_call: dict[str, Any] | None = None


class WardResponse(BaseModel):
    beds: list[RawBed]
    received_at: int


class ActionEntry(BaseModel):
    id: str
    occurred_at: int
    actor: str
    action_code: str
    action: str
    bed_id: str | None
    device_id: str | None
    approved_by: str | None
    mode: Literal["automatic", "person"]
    undoable: bool
    references_action_id: str | None


class ActionsResponse(BaseModel):
    actions: list[ActionEntry]


class DeviceEntry(BaseModel):
    device_id: str
    bed_id: str
    online: bool
    isolated: bool
    isolated_since: int | None
    last_seen_ts: int | None
    net: dict[str, Any] | None
    # Newest non-null net_features.senders in the buffered rows (the newest row may not know it).
    senders: float | None = None
    senders_window_start: int | None = None


class HealthResponse(BaseModel):
    ok: bool
    mqtt_connected: bool
    db_ok: bool
    storage: Literal["memory", "postgresql"]
    durable: bool = False
    beds_online: int
    last_message_ts: int | None
    invalid_messages: int
    pending_publications: int
    db_queued_rows: int = 0


# --------------------------------------------------------------------------- Phase B inputs

_ID = r"^[A-Za-z0-9][A-Za-z0-9_.:@-]{0,127}$"


class ManualReading(BedCommand):
    """record_manual_reading; heartRate is the screen's name for hr. At least one value is required."""
    type: Literal["record_manual_reading"] | None = None
    heartRate: float | None = Field(default=None, ge=0, le=400)
    hr: float | None = Field(default=None, ge=0, le=400)
    spo2: float | None = Field(default=None, ge=0, le=100)
    sys: float | None = Field(default=None, ge=0, le=400)
    dia: float | None = Field(default=None, ge=0, le=400)
    rr: float | None = Field(default=None, ge=0, le=200)

    @model_validator(mode="after")
    def one_value(self):
        if self.heartRate is not None and self.hr is not None and self.heartRate != self.hr:
            raise ValueError("heartRate and hr disagree")
        if all(v is None for v in (self.heartRate, self.hr, self.spo2, self.sys, self.dia, self.rr)):
            raise ValueError("at least one of hr, spo2, sys, dia, rr is required")
        return self


class CallNurse(BedCommand):
    type: Literal["call_bedside_nurse"] | None = None
    requestedBy: str | None = None  # ignored: the caller is the logged-in person
    urgency: Literal["routine", "urgent"] = "routine"


class Assign(BedCommand):
    type: Literal["assign_clinician"] | None = None
    clinicianId: str = Field(pattern=_ID)


class AssignmentStatus(BedCommand):
    type: Literal["update_assignment"] | None = None
    status: Literal["assigned", "on_my_way", "reviewing", "complete"]


class FleetHunt(Input):
    type: Literal["fleet_hunt"] | None = None
    model: str = Field(default="all", min_length=1, max_length=128)
    notes: str = Field(default="", max_length=4000)


class IncidentCommand(BedCommand):
    type: Literal["capture_evidence", "contain_incident", "resolve_incident"] | None = None
    incidentId: str | None = None
    reason: str = Field(default="", max_length=4000)


class ReviewReport(Input):
    type: Literal["review_report"] | None = None
    incidentId: str | None = None
    notes: str = Field(default="", max_length=4000)


class CreateTicket(Input):
    type: Literal["create_ticket"] | None = None
    bedId: str
    issue: str = Field(min_length=1, max_length=2000)
    notes: str = Field(default="", max_length=4000)


class UpdateTicket(Input):
    type: Literal["update_ticket"] | None = None
    ticketId: str | None = None
    status: Literal["open", "assigned", "resolved"] | None = None
    note: str | None = Field(default=None, max_length=4000)

    @model_validator(mode="after")
    def something(self):
        if self.status is None and self.note is None:
            raise ValueError("status or note is required")
        return self


class SaveReport(Input):
    """save_report: the screen sends {report: CertReportDraft}; {data: {...}} is also accepted."""
    model_config = ConfigDict(strict=False, extra="ignore")
    type: Literal["save_report"] | None = None
    incidentId: str | None = None
    report: dict[str, Any] | None = None
    data: dict[str, Any] | None = None

    @model_validator(mode="after")
    def one_body(self):
        if (self.report is None) == (self.data is None):
            raise ValueError("send exactly one of report or data")
        return self


class MarkSent(Input):
    type: Literal["mark_report_sent"] | None = None
    incidentId: str | None = None
    sentBy: str | None = None  # ignored: the sender is the logged-in person


# --------------------------------------------------------------------------- Phase B outputs

class RecordOut(BaseModel):
    record_id: str
    kind: Literal["ticket", "report", "incident", "briefing", "workload"]
    ts: int
    by: str
    version: int
    data: dict[str, Any]
    updated_ts: int | None
    updated_by: str | None


class BedDetail(RawBed):
    scores: dict[str, dict[str, Any]]
    recent_verdicts: list[dict[str, Any]]
    device: dict[str, Any]
    open_alerts: list[dict[str, Any]]
    monitor_alarm: dict[str, Any] | None = None


class HistoryPoint(BaseModel):
    ts: int
    hr: float | None
    spo2: float | None
    rr: float | None
    sys: float | None
    dia: float | None
    map: float | None
    abp_mean: float | None
    verdict: str | None
    trusted: bool


class HistoryResponse(BaseModel):
    bed_id: str
    points: list[HistoryPoint]


class BlindTime(BaseModel):
    bed_id: str
    minutes: float = Field(ge=0)


class BriefingResponse(BaseModel):
    since: str
    generated_by: str
    summary: str
    incidents: int = Field(ge=0)
    untrusted_beds: int = Field(ge=0)
    open_tickets: int = Field(ge=0)
    blind_time: list[BlindTime]
    record_id: str
    ts: int
    # The A8 record's own facts, i.e. the numbers the summary text was written from.
    facts: dict[str, Any] | None = None
    fallback_reason: str | None = None


class NurseLoad(BaseModel):
    nurse_id: str
    nurse_name: str
    role: str | None = None
    alarms_last_2h: int = Field(ge=0)


class WorkloadResponse(BaseModel):
    nurses: list[NurseLoad]
    record_id: str | None = None
    ts: int | None = None

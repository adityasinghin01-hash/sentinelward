"""HTTP contracts; MQTT messages remain sw_common dictionaries."""
from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator

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
    start_at_s: int = Field(default=0, ge=0)


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
    bed_id: str
    device_id: str
    patient: Patient | None = None
    verdict: Verdict
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
    display: Literal["live", "last_trusted", "offline"]
    offline_since: int | None
    manual: dict[str, Any] | None = None
    last_bedside_check: dict[str, Any] | None = None


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


class HealthResponse(BaseModel):
    ok: bool
    mqtt_connected: bool
    db_ok: bool
    storage: Literal["memory"]
    durable: bool = False
    beds_online: int
    last_message_ts: int | None
    invalid_messages: int
    pending_publications: int

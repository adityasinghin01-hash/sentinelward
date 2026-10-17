"""sw_data: turn PhysioNet/CinC 2015, MIMIC-III and VitalDB recordings into SentinelWard bed packs."""
from __future__ import annotations

LOADER_VERSION = "1.3.0"   # 1.3.0: optional second ECG lead (ecg2)

#: Output sample rate of every waveform in a pack.
FS_OUT = 125

#: Constant some datasets (VTaC and others) use for a missing lead.
MISSING_SENTINEL = -32768.0

#: Explicit little-endian float32, so packs load correctly on big-endian LinuxONE.
PACK_DTYPE = "<f4"

#: PhysioNet/CinC 2015 header comment -> alarm code.
ALARM_CODES = {
    "Asystole": "ASYSTOLE",
    "Bradycardia": "BRADY",
    "Tachycardia": "TACHY",
    "Ventricular_Tachycardia": "VTACH",
    "Ventricular_Flutter_Fib": "VFIB",
}

#: Alarm priority (SentinelWard choice).
ALARM_PRIORITY = {
    "ASYSTOLE": "high",
    "VTACH": "high",
    "VFIB": "high",
    "BRADY": "medium",
    "TACHY": "medium",
}

#: The 2015 monitor alarm sounds at exactly 300 s into every record.
CINC_ALARM_T_S = 300

VITAL_ENDIAN_MESSAGE = (
    "VitalDB files must be converted on a little-endian machine (Mac or Colab); "
    "vitaldb reads them wrongly on LinuxONE."
)


class BedError(Exception):
    """A bed cannot be built; carries the bed ID and a human-readable reason."""

    def __init__(self, bed_id: str, reason: str) -> None:
        self.bed_id = bed_id
        self.reason = reason
        super().__init__(f"{bed_id}: {reason}")


class EndianError(RuntimeError):
    """Raised when a .vital file would be read on a big-endian machine."""

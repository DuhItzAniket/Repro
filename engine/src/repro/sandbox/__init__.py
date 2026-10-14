"""Running target code in isolation (ADR-0004): the process sandbox, L0 to L2 (D01)."""

from repro.sandbox.detect import Detection, Detections, read_detections
from repro.sandbox.evidence import detection_evidence
from repro.sandbox.limits import GIB, MIB, Limits
from repro.sandbox.process import (
    Execution,
    ProcessSandbox,
    SandboxError,
    containment,
)

__all__ = [
    "GIB",
    "MIB",
    "Detection",
    "Detections",
    "Execution",
    "Limits",
    "ProcessSandbox",
    "SandboxError",
    "containment",
    "detection_evidence",
    "read_detections",
]

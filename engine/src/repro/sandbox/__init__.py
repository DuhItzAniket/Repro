"""Running target code in isolation (ADR-0004): processes at L0 to L2 (D01), containers at L3
(D02)."""

from repro.sandbox.detect import Detection, Detections, read_detections
from repro.sandbox.docker import DEFAULT_IMAGE, DockerSandbox, docker_available
from repro.sandbox.evidence import detection_evidence
from repro.sandbox.limits import GIB, MIB, Limits
from repro.sandbox.process import (
    Execution,
    ProcessSandbox,
    SandboxError,
    containment,
)

__all__ = [
    "DEFAULT_IMAGE",
    "GIB",
    "MIB",
    "Detection",
    "Detections",
    "DockerSandbox",
    "Execution",
    "Limits",
    "ProcessSandbox",
    "SandboxError",
    "containment",
    "detection_evidence",
    "docker_available",
    "read_detections",
]

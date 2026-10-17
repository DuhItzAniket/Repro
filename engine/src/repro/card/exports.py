"""The card in formats other tools read (H04): an in-toto attestation, SARIF 2.1.0, JUnit XML.

Each is made from the card a run published and the evidence records in its log. Each says only
what the card says: none passes what the card flags, and what could not be checked stays so.

**in-toto** (ADR-0012). A Statement v1 (https://github.com/in-toto/attestation/blob/main/spec/
v1/statement.md, checked 2026-10-17) whose subject is the head commit (``gitCommit``) and whose
predicate (``reproduction-card-v0.schema.json``) holds the card itself, its digest, the evidence
it cites as digested resource descriptors and the event log's digest. The predicate's type
carries its major version, as the spec's TypeURI asks, and resolves to its description. Local
statements are unsigned: signing belongs to CI (I03). ``card_from_attestation`` takes a card
back out, checking every digest and copy, so card -> attestation -> card is exact.

**SARIF** (OASIS SARIF 2.1.0, Errata 01, https://docs.oasis-open.org/sarif/sarif/v2.1.0/
errata01/os/sarif-v2.1.0-errata01-os-complete.html, checked 2026-10-17). One result per gap
item, failed invariant, judged claim and missing item. ``kind`` says what the result is (§3.27.9):
``fail`` for a problem (``level`` error for what flags the change, warning otherwise),
``review`` for a difference a person must judge, ``open`` for what could not be decided (a
missing item, an unverifiable claim), ``informational`` and ``pass`` for the rest; any other
kind than ``fail`` has ``level`` none (§3.27.10). Locations are the files the evidence names.

**JUnit** (Apache Ant's format, as the JUnit.xsd of github.com/windyroad/JUnit-Schema describes
it). One test case per claim (supported: passed; contradicted: a failure; unverifiable or
unjudged: skipped) and one for the card's status (VERIFIED: passed; FLAGGED: a failure;
UNVERIFIABLE: an error). The missing items go to ``system-out``.
"""

import re
from collections.abc import Iterator, Mapping, Sequence
from typing import Any, Final
from xml.etree import ElementTree as ET

from repro.card.assemble import canonical, digest

STATEMENT_TYPE: Final = "https://in-toto.io/Statement/v1"
PREDICATE_TYPE: Final = (
    "https://github.com/DuhItzAniket/Repro/blob/main/docs/attestation/reproduction-card/v0.md"
)
EVIDENCE_MEDIA_TYPE: Final = "application/vnd.repro.evidence+json"
NOTICE: Final = (
    "This attestation records what Repro ran and observed for one change. It does not certify "
    "that the change is correct, and verdicts from language models are judgements."
)
SARIF_SCHEMA: Final = (
    "https://docs.oasis-open.org/sarif/sarif/v2.1.0/errata01/os/schemas/sarif-schema-2.1.0.json"
)
INFORMATION_URI: Final = "https://github.com/DuhItzAniket/Repro"
_EVIDENCE_ID: Final = re.compile(r"^ev_[0-9A-HJKMNP-TV-Z]{26}$")


class AttestationError(ValueError):
    """An attestation that is not Repro's, or whose card does not match its digests."""


# -- in-toto -----------------------------------------------------------------------------------


def cited(value: Any) -> Iterator[str]:
    """Every evidence ID ``value`` holds, at any depth, in order of first appearance."""
    seen: set[str] = set()
    stack = [value]
    while stack:
        item = stack.pop()
        if isinstance(item, str):
            if _EVIDENCE_ID.match(item) and item not in seen:
                seen.add(item)
                yield item
        elif isinstance(item, Mapping):
            stack.extend(reversed([item[key] for key in sorted(item)]))
        elif isinstance(item, list):
            stack.extend(reversed(item))


def attestation(
    card: Mapping[str, Any], evidence: Mapping[str, Mapping[str, Any]]
) -> dict[str, Any]:
    """An unsigned in-toto Statement for ``card``; ``evidence`` holds the run's evidence records
    by ID (each the card cites must be there)."""
    conditions = card["conditions"]
    head = (conditions.get("head") or {}).get("sha")
    if not head:
        raise AttestationError("the card names no head commit to attest")
    descriptors = []
    for evidence_id in sorted(cited(card)):
        record = evidence.get(evidence_id)
        if record is None:
            raise AttestationError(f"the card cites {evidence_id}, which the log does not hold")
        descriptors.append(
            {
                "name": evidence_id,
                "digest": {"sha256": digest(canonical(record))},
                "mediaType": EVIDENCE_MEDIA_TYPE,
            }
        )
    replay = card["replay"]
    return {
        "_type": STATEMENT_TYPE,
        "subject": [{"name": card["repo"]["name"], "digest": {"gitCommit": head}}],
        "predicateType": PREDICATE_TYPE,
        "predicate": {
            "card": dict(card),
            "cardDigest": {"sha256": digest(canonical(card))},
            "status": card["status"],
            "isolationLevel": conditions.get("isolation_level"),
            "network": conditions.get("network"),
            "eventLog": {
                "digest": {"sha256": replay["event_log_sha256"]},
                "eventCount": replay["event_count"],
            },
            "evidence": descriptors,
            "verifier": {"name": "repro", "version": str(conditions.get("repro_version") or "?")},
            "notice": NOTICE,
        },
    }


def card_from_attestation(statement: Mapping[str, Any]) -> dict[str, Any]:
    """The card ``statement`` holds, after checking that it is Repro's predicate and that the
    card matches its digest, its subject and the copies beside it."""
    if statement.get("_type") != STATEMENT_TYPE:
        raise AttestationError(f"not an in-toto Statement v1: _type {statement.get('_type')!r}")
    if statement.get("predicateType") != PREDICATE_TYPE:
        raise AttestationError(
            f"not a Repro card: predicateType {statement.get('predicateType')!r}"
        )
    predicate = statement.get("predicate")
    if not isinstance(predicate, Mapping) or not isinstance(predicate.get("card"), Mapping):
        raise AttestationError("the predicate holds no card")
    card = dict(predicate["card"])
    if predicate.get("cardDigest", {}).get("sha256") != digest(canonical(card)):
        raise AttestationError("the card does not match its digest")
    head = card["conditions"]["head"]["sha"]
    own = predicate["cardDigest"]["sha256"]
    subjects = [s.get("digest", {}) for s in statement.get("subject", [])]
    # Repro's export names the head commit; signed through GitHub (I03), whose attestations take
    # sha256 subjects, the subject is the card itself, as canonical JSON.
    if not any(d.get("gitCommit") == head or d.get("sha256") == own for d in subjects):
        raise AttestationError(f"no subject is the card's head commit {head} or the card itself")
    conditions = card["conditions"]
    copies = {
        "status": card["status"],
        "isolationLevel": conditions.get("isolation_level"),
        "network": conditions.get("network"),
    }
    for field, value in copies.items():
        if predicate.get(field) != value:
            raise AttestationError(f"the predicate's {field} is not the card's")
    return card


# -- SARIF -------------------------------------------------------------------------------------


def _location(target: Mapping[str, Any]) -> dict[str, Any] | None:
    """A SARIF location for an evidence target: the file it names, or its symbol."""
    path = target.get("file") or (
        str(target["test"]).split("::")[0] if target.get("test") else None
    )
    if path:
        return {"physicalLocation": {"artifactLocation": {"uri": str(path).replace("\\", "/")}}}
    if target.get("symbol"):
        return {"logicalLocations": [{"fullyQualifiedName": str(target["symbol"])}]}
    return None


def _locations(evidence_ids: Sequence[str], evidence: Mapping[str, Mapping[str, Any]]) -> list[Any]:
    found = []
    for evidence_id in evidence_ids:
        for target in (evidence.get(evidence_id) or {}).get("targets", []):
            location = _location(target)
            if location is not None and location not in found:
                found.append(location)
    return found


#: A gap item's resolution (F04) as SARIF's kind and level.
_GAP: Final = {
    "flagged": ("fail", "error"),
    "unassessed": ("review", "none"),
    "pre-existing": ("informational", "none"),
    "explained": ("pass", "none"),
    "passed": ("pass", "none"),
}
_VERDICT: Final = {
    "contradicted": ("fail", "error"),
    "unverifiable": ("open", "none"),
    "supported": ("pass", "none"),
}


def sarif(card: Mapping[str, Any], evidence: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    """A SARIF 2.1.0 log of ``card``: one run, Repro's."""
    rules: dict[str, dict[str, Any]] = {}
    results: list[dict[str, Any]] = []

    def add(
        rule: str, describe: str, *, judged: tuple[str, str], text: str, ids: Sequence[str]
    ) -> None:
        kind, level = judged
        rules.setdefault(rule, {"id": rule, "shortDescription": {"text": describe}})
        result: dict[str, Any] = {
            "ruleId": rule,
            "kind": kind,
            "level": level,
            "message": {"text": text},
        }
        locations = _locations(ids, evidence)
        if locations:
            result["locations"] = locations
        if ids:
            result["properties"] = {"evidenceIds": list(ids)}
        results.append(result)

    for item in card["gap"]:
        rule = f"{item['check']}/{item['kind']}"
        add(rule, f"{item['check']}: {item['kind']}", judged=_GAP[item["resolution"]],
            text=item["summary"], ids=[item["evidence_id"]])  # fmt: skip
    for invariant in card["invariants"]:
        if invariant["result"] != "pass":
            judged = ("fail", "error") if invariant["result"] == "fail" else ("open", "none")
            add(f"invariant/{invariant['name']}", f"invariant {invariant['name']}", judged=judged,
                text=invariant["message"], ids=invariant["evidence_ids"])  # fmt: skip
    claims = {claim["id"]: claim for claim in card["claims"]}
    for verdict in card["verdicts"]:
        claim = claims.get(verdict["claim_id"], {})
        said = claim.get("text", verdict["claim_id"])
        add(f"claim/{verdict['verdict']}", f"a claim judged {verdict['verdict']}",
            judged=_VERDICT[verdict["verdict"]],
            text=f"{verdict['verdict']}: {said}: {verdict['rationale']}"[:4000],
            ids=verdict["cited_evidence"])  # fmt: skip
    for missing in card["missing"]:
        add(f"missing/{missing['reason']}", f"not checked: {missing['reason']}",
            judged=("open", "none"), text=missing["detail"], ids=[])  # fmt: skip
    head = card["conditions"]["head"]
    run: dict[str, Any] = {
        "tool": {
            "driver": {
                "name": "Repro",
                "version": str(card["conditions"].get("repro_version") or "?"),
                "informationUri": INFORMATION_URI,
                "rules": [rules[rule] for rule in sorted(rules)],
            }
        },
        "results": results,
        "properties": {
            "status": card["status"],
            "runId": card["run_id"],
            "headCommit": head.get("sha") if head else None,
            "isolationLevel": card["conditions"].get("isolation_level"),
            "network": card["conditions"].get("network"),
        },
    }
    return {"$schema": SARIF_SCHEMA, "version": "2.1.0", "runs": [run]}


# -- JUnit -------------------------------------------------------------------------------------


def _timestamp(generated_at: str) -> str:
    """The card's time as JUnit.xsd's ISO 8601 pattern: seconds, no zone (it is UTC)."""
    return generated_at[:19]


def junit(card: Mapping[str, Any]) -> bytes:
    """A JUnit XML report of ``card``: one test case per claim, one for the status."""
    suite = ET.Element("testsuite")
    properties = ET.SubElement(suite, "properties")
    head = card["conditions"]["head"]
    for name, value in (
        ("repro.run_id", card["run_id"]),
        ("repro.status", card["status"]),
        ("repro.head", (head or {}).get("sha") or ""),
        ("repro.isolation_level", card["conditions"].get("isolation_level") or ""),
        ("repro.network", card["conditions"].get("network") or ""),
        ("repro.card_sha256", digest(canonical(card))),
    ):
        ET.SubElement(properties, "property", name=name, value=str(value))
    counts = {"tests": 0, "failures": 0, "errors": 0, "skipped": 0}

    def case(classname: str, name: str, outcome: str | None, kind: str, text: str) -> None:
        counts["tests"] += 1
        element = ET.SubElement(suite, "testcase", name=name or "-", classname=classname, time="0")
        if outcome is not None:
            counts[{"failure": "failures", "error": "errors", "skipped": "skipped"}[outcome]] += 1
            child = ET.SubElement(element, outcome, message=text[:1000])
            if outcome != "skipped":
                child.set("type", kind)
                child.text = text

    verdicts = {v["claim_id"]: v for v in card["verdicts"]}
    for claim in card["claims"]:
        verdict = verdicts.get(claim["id"])
        name = f"{claim['id']}: {claim['text']}"
        if verdict is None:
            case("repro.claims", name, "skipped", "unjudged", "not judged")
        elif verdict["verdict"] == "supported":
            case("repro.claims", name, None, "supported", "")
        elif verdict["verdict"] == "contradicted":
            case("repro.claims", name, "failure", "contradicted", verdict["rationale"])
        else:
            case(
                "repro.claims",
                name,
                "skipped",
                "unverifiable",
                f"unverifiable: {verdict['rationale']}",
            )
    reasons = "\n".join(f"{r['rule']}: {r['detail']}" for r in card["status_reasons"])
    outcome = {"VERIFIED": None, "FLAGGED": "failure", "UNVERIFIABLE": "error"}[card["status"]]
    case(
        "repro.card",
        f"status: {card['status']}",
        outcome,
        card["status"],
        reasons or card["status"],
    )
    missing = [f"{m['reason']}: {m['detail']}" for m in card["missing"]]
    ET.SubElement(suite, "system-out").text = (
        "\n".join(["Not checked:", *missing]) if missing else ""
    )
    ET.SubElement(suite, "system-err").text = ""
    suite.set("name", f"repro {card['repo']['name']}")
    suite.set("timestamp", _timestamp(card["generated_at"]))
    suite.set("hostname", "repro")  # not the machine's: a report may be shared
    for key, value in counts.items():
        suite.set(key, str(value))
    suite.set("time", "0")
    data: bytes = ET.tostring(suite, encoding="utf-8", xml_declaration=True)
    return data + b"\n"

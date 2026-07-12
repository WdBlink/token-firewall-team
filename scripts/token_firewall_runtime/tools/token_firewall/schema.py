from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable


DEFAULT_SCHEMA_DIR = Path(__file__).with_name("schemas")


@dataclass(frozen=True)
class ValidationIssue:
    path: str
    message: str
    keyword: str

    def __str__(self) -> str:
        return f"{self.path}: {self.message} [{self.keyword}]"


class SchemaValidationError(ValueError):
    def __init__(self, schema_id: str, issues: Iterable[ValidationIssue]):
        self.schema_id = schema_id
        self.issues = tuple(issues)
        message = "; ".join(str(issue) for issue in self.issues)
        super().__init__(f"{schema_id} validation failed: {message}")


def canonical_json_bytes(value: Any, *, exclude_content_hash: bool = False) -> bytes:
    if exclude_content_hash and isinstance(value, dict):
        value = {key: item for key, item in value.items() if key != "content_sha256"}
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def canonical_sha256(value: Any, *, exclude_content_hash: bool = True) -> str:
    return hashlib.sha256(canonical_json_bytes(value, exclude_content_hash=exclude_content_hash)).hexdigest()


class SchemaRegistry:
    """Load protocol schemas and validate the Draft 2020-12 subset used by the POC.

    The repository intentionally has no third-party Python dependencies. The protocol
    remains ordinary JSON Schema and can later be handed to jsonschema or Ajv without
    changing the object format. This validator fails closed on malformed local refs and
    supports every keyword present in the bundled schemas.
    """

    def __init__(self, schema_dir: Path | str = DEFAULT_SCHEMA_DIR):
        self.schema_dir = Path(schema_dir)
        self.schemas: dict[str, dict[str, Any]] = {}
        for path in sorted(self.schema_dir.glob("*.schema.json")):
            schema = json.loads(path.read_text(encoding="utf-8"))
            schema_id = schema.get("$id")
            if not isinstance(schema_id, str) or not schema_id:
                raise ValueError(f"schema has no $id: {path}")
            if schema.get("$schema") != "https://json-schema.org/draft/2020-12/schema":
                raise ValueError(f"schema is not Draft 2020-12: {path}")
            if schema_id in self.schemas:
                raise ValueError(f"duplicate schema id: {schema_id}")
            self.schemas[schema_id] = schema
        if not self.schemas:
            raise ValueError(f"no schemas found in {self.schema_dir}")

    def validate(
        self,
        instance: Any,
        schema_id: str | None = None,
        *,
        check_semantics: bool = True,
    ) -> None:
        selected = schema_id or (instance.get("schema") if isinstance(instance, dict) else None)
        if not isinstance(selected, str) or selected not in self.schemas:
            raise SchemaValidationError(
                str(selected),
                [ValidationIssue("$", "unknown or missing schema id", "schema")],
            )
        root = self.schemas[selected]
        issues = self._validate_node(instance, root, root, "$")
        if check_semantics and not issues:
            issues.extend(self._semantic_issues(selected, instance))
        if issues:
            raise SchemaValidationError(selected, issues)

    def is_valid(self, instance: Any, schema_id: str | None = None) -> bool:
        try:
            self.validate(instance, schema_id)
        except SchemaValidationError:
            return False
        return True

    def _resolve_ref(self, ref: str, root: dict[str, Any]) -> dict[str, Any]:
        if not ref.startswith("#/"):
            raise ValueError(f"only local JSON pointers are supported: {ref}")
        node: Any = root
        for raw_part in ref[2:].split("/"):
            part = raw_part.replace("~1", "/").replace("~0", "~")
            if not isinstance(node, dict) or part not in node:
                raise ValueError(f"unresolvable JSON pointer: {ref}")
            node = node[part]
        if not isinstance(node, dict):
            raise ValueError(f"JSON pointer does not target a schema object: {ref}")
        return node

    def _validate_node(
        self,
        instance: Any,
        schema: dict[str, Any],
        root: dict[str, Any],
        path: str,
    ) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []

        if "$ref" in schema:
            try:
                target = self._resolve_ref(schema["$ref"], root)
            except ValueError as exc:
                return [ValidationIssue(path, str(exc), "$ref")]
            return self._validate_node(instance, target, root, path)

        if "allOf" in schema:
            for branch in schema["allOf"]:
                issues.extend(self._validate_node(instance, branch, root, path))

        if "anyOf" in schema:
            branch_results = [self._validate_node(instance, branch, root, path) for branch in schema["anyOf"]]
            if not any(not result for result in branch_results):
                issues.append(ValidationIssue(path, "does not match any allowed branch", "anyOf"))

        if "oneOf" in schema:
            branch_results = [self._validate_node(instance, branch, root, path) for branch in schema["oneOf"]]
            matches = sum(not result for result in branch_results)
            if matches != 1:
                issues.append(ValidationIssue(path, f"must match exactly one branch; matched {matches}", "oneOf"))

        if "not" in schema and not self._validate_node(instance, schema["not"], root, path):
            issues.append(ValidationIssue(path, "matches a forbidden schema", "not"))

        if "const" in schema and instance != schema["const"]:
            issues.append(ValidationIssue(path, f"must equal {schema['const']!r}", "const"))
        if "enum" in schema and instance not in schema["enum"]:
            issues.append(ValidationIssue(path, f"must be one of {schema['enum']!r}", "enum"))

        expected_type = schema.get("type")
        if expected_type is not None:
            allowed = expected_type if isinstance(expected_type, list) else [expected_type]
            if not any(self._matches_type(instance, item) for item in allowed):
                return issues + [ValidationIssue(path, f"expected type {allowed!r}", "type")]

        if isinstance(instance, dict):
            required = schema.get("required", [])
            for key in required:
                if key not in instance:
                    issues.append(ValidationIssue(path, f"missing required property {key!r}", "required"))

            properties = schema.get("properties", {})
            for key, value in instance.items():
                child_path = f"{path}.{key}"
                if key in properties:
                    issues.extend(self._validate_node(value, properties[key], root, child_path))
                elif schema.get("additionalProperties") is False:
                    issues.append(ValidationIssue(child_path, "additional property is not allowed", "additionalProperties"))
                elif isinstance(schema.get("additionalProperties"), dict):
                    issues.extend(self._validate_node(value, schema["additionalProperties"], root, child_path))

        if isinstance(instance, list):
            if "minItems" in schema and len(instance) < schema["minItems"]:
                issues.append(ValidationIssue(path, f"must contain at least {schema['minItems']} items", "minItems"))
            if "maxItems" in schema and len(instance) > schema["maxItems"]:
                issues.append(ValidationIssue(path, f"must contain at most {schema['maxItems']} items", "maxItems"))
            if schema.get("uniqueItems"):
                markers = [canonical_json_bytes(item) for item in instance]
                if len(set(markers)) != len(markers):
                    issues.append(ValidationIssue(path, "items must be unique", "uniqueItems"))
            if isinstance(schema.get("items"), dict):
                for index, value in enumerate(instance):
                    issues.extend(self._validate_node(value, schema["items"], root, f"{path}[{index}]"))

        if isinstance(instance, str):
            if "minLength" in schema and len(instance) < schema["minLength"]:
                issues.append(ValidationIssue(path, f"must be at least {schema['minLength']} characters", "minLength"))
            if "maxLength" in schema and len(instance) > schema["maxLength"]:
                issues.append(ValidationIssue(path, f"must be at most {schema['maxLength']} characters", "maxLength"))
            if "pattern" in schema and re.search(schema["pattern"], instance) is None:
                issues.append(ValidationIssue(path, f"does not match {schema['pattern']!r}", "pattern"))
            if schema.get("format") == "date-time" and not self._is_datetime(instance):
                issues.append(ValidationIssue(path, "must be an ISO 8601 date-time with timezone", "format"))

        if self._matches_type(instance, "number"):
            if "minimum" in schema and instance < schema["minimum"]:
                issues.append(ValidationIssue(path, f"must be >= {schema['minimum']}", "minimum"))
            if "maximum" in schema and instance > schema["maximum"]:
                issues.append(ValidationIssue(path, f"must be <= {schema['maximum']}", "maximum"))

        return issues

    @staticmethod
    def _matches_type(instance: Any, expected: str) -> bool:
        match expected:
            case "object":
                return isinstance(instance, dict)
            case "array":
                return isinstance(instance, list)
            case "string":
                return isinstance(instance, str)
            case "integer":
                return isinstance(instance, int) and not isinstance(instance, bool)
            case "number":
                return isinstance(instance, (int, float)) and not isinstance(instance, bool) and math.isfinite(instance)
            case "boolean":
                return isinstance(instance, bool)
            case "null":
                return instance is None
            case _:
                return False

    @staticmethod
    def _is_datetime(value: str) -> bool:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return False
        return parsed.tzinfo is not None

    @staticmethod
    def _duplicates(values: Iterable[str]) -> set[str]:
        seen: set[str] = set()
        duplicates: set[str] = set()
        for value in values:
            if value in seen:
                duplicates.add(value)
            seen.add(value)
        return duplicates

    def _semantic_issues(self, schema_id: str, instance: dict[str, Any]) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []
        if schema_id in {
            "token-firewall/mission-contract@0.1",
            "token-firewall/work-order@0.1",
            "token-firewall/work-order@0.2",
            "token-firewall/delivery-manifest@0.1",
            "token-firewall/review-packet@0.1",
            "token-firewall/external-observability-policy@0.1",
            "token-firewall/evaluation-protocol@0.1",
            "token-firewall/evaluation-pair@0.1",
            "token-firewall/evaluation-summary@0.1",
            "token-firewall/evaluation-lab-manifest@0.1",
            "token-firewall/risk-token-budget-policy@0.1",
        }:
            actual_hash = canonical_sha256(instance)
            if instance.get("content_sha256") != actual_hash:
                issues.append(
                    ValidationIssue(
                        "$.content_sha256",
                        f"does not match canonical object content; expected {actual_hash}",
                        "contentHash",
                    )
                )

        if schema_id == "token-firewall/mission-contract@0.1":
            declared = {item["id"] for item in instance["success_outcomes"]}
            declared.update(item["id"] for item in instance["invariants"])
            unknown = sorted(set(instance["overall_acceptance"]) - declared)
            if unknown:
                issues.append(ValidationIssue("$.overall_acceptance", f"references unknown ids: {unknown}", "reference"))

        elif schema_id in {"token-firewall/work-order@0.1", "token-firewall/work-order@0.2"}:
            task_id = instance["task_id"]
            if task_id in instance["dependencies"]:
                issues.append(ValidationIssue("$.dependencies", "task cannot depend on itself", "reference"))
            spec_ids = [item["id"] for item in instance["acceptance_specs"]]
            duplicates = self._duplicates(spec_ids)
            if duplicates:
                issues.append(ValidationIssue("$.acceptance_specs", f"duplicate spec ids: {sorted(duplicates)}", "unique"))
            if schema_id == "token-firewall/work-order@0.2":
                for index, spec in enumerate(instance["acceptance_specs"]):
                    case_ids = [item["case_id"] for item in (*spec["positive_cases"], *spec["negative_cases"])]
                    boundary_ids = [item["boundary_id"] for item in spec["semantic_boundaries"]]
                    if self._duplicates(case_ids):
                        issues.append(ValidationIssue(f"$.acceptance_specs[{index}]", "case ids must be unique", "unique"))
                    if self._duplicates(boundary_ids):
                        issues.append(ValidationIssue(f"$.acceptance_specs[{index}].semantic_boundaries", "boundary ids must be unique", "unique"))
                    for boundary_index, boundary in enumerate(spec["semantic_boundaries"]):
                        if boundary["inside"].strip().casefold() == boundary["outside"].strip().casefold():
                            issues.append(
                                ValidationIssue(
                                    f"$.acceptance_specs[{index}].semantic_boundaries[{boundary_index}]",
                                    "inside and outside examples must differ",
                                    "semanticBoundary",
                                )
                            )

        elif schema_id == "token-firewall/delivery-manifest@0.1":
            if instance["base_commit"] == instance["head_commit"]:
                issues.append(ValidationIssue("$.head_commit", "head commit must differ from base commit", "commitRange"))
            spec_ids = [item["spec_id"] for item in instance["spec_results"]]
            duplicates = self._duplicates(spec_ids)
            if duplicates:
                issues.append(ValidationIssue("$.spec_results", f"duplicate spec results: {sorted(duplicates)}", "unique"))
            paths = [item["path"] for item in instance["changed_files"]]
            duplicates = self._duplicates(paths)
            if duplicates:
                issues.append(ValidationIssue("$.changed_files", f"duplicate paths: {sorted(duplicates)}", "unique"))

        elif schema_id == "token-firewall/review-packet@0.1":
            for index, item in enumerate(instance["context_slices"]):
                if item["end"] < item["start"]:
                    issues.append(ValidationIssue(f"$.context_slices[{index}]", "end must be >= start", "range"))
            budget = instance["packet_budget"]
            if budget["estimated_tokens"] > budget["max_tokens"]:
                issues.append(ValidationIssue("$.packet_budget", "declared estimate exceeds maximum", "budget"))

        elif schema_id == "token-firewall/review-verdict@0.1":
            verdict = instance["verdict"]
            severe = [item for item in instance["findings"] if item["severity"] in {"high", "critical"}]
            if verdict == "PASS" and (severe or instance["coverage_gaps"] or instance["requested_context"]):
                issues.append(
                    ValidationIssue(
                        "$.verdict",
                        "PASS cannot retain high/critical findings, coverage gaps, or context requests",
                        "verdict",
                    )
                )
            if verdict == "REWORK" and not instance["findings"]:
                issues.append(ValidationIssue("$.findings", "REWORK requires at least one structured finding", "verdict"))
            if verdict == "ESCALATE" and not instance.get("escalation_reason"):
                issues.append(ValidationIssue("$.escalation_reason", "ESCALATE requires a reason", "verdict"))

        elif schema_id == "token-firewall/runtime-worker-report@0.1":
            status = instance["status"]
            if status == "DELIVERED" and instance["commit"] is None:
                issues.append(ValidationIssue("$.commit", "DELIVERED requires a commit", "workerStatus"))
            if status != "DELIVERED" and instance["commit"] is not None:
                issues.append(
                    ValidationIssue("$.commit", "only DELIVERED can claim a Worker-created commit", "workerStatus")
                )
            if status in {"BLOCKED", "NEEDS_REPLAN"} and not instance["blockers"]:
                issues.append(
                    ValidationIssue("$.blockers", "BLOCKED/NEEDS_REPLAN requires blockers", "workerStatus")
                )
            if status == "CHANGES_READY" and instance["blockers"]:
                issues.append(ValidationIssue("$.blockers", "CHANGES_READY cannot retain blockers", "workerStatus"))
            for index, item in enumerate(instance["context_slices"]):
                if item["end"] < item["start"]:
                    issues.append(ValidationIssue(f"$.context_slices[{index}]", "end must be >= start", "range"))
            spec_ids = [item["spec_id"] for item in instance["spec_results"]]
            duplicates = self._duplicates(spec_ids)
            if duplicates:
                issues.append(ValidationIssue("$.spec_results", f"duplicate spec results: {sorted(duplicates)}", "unique"))

        elif schema_id == "token-firewall/runtime-verifier-report@0.1":
            status = instance["status"]
            failed_specs = [item for item in instance["spec_results"] if item["status"] != "pass"]
            severe = [item for item in instance["findings"] if item["severity"] in {"high", "critical"}]
            if status == "PASS" and (
                failed_specs
                or severe
                or instance["coverage_gaps"]
                or instance["requested_context"]
            ):
                issues.append(
                    ValidationIssue(
                        "$.status",
                        "PASS requires all specs pass, no high/critical finding, no coverage gap, and no context request",
                        "verifierStatus",
                    )
                )
            if status == "FAIL" and not (failed_specs or instance["findings"] or instance["coverage_gaps"]):
                issues.append(
                    ValidationIssue("$.status", "FAIL requires a failed spec, finding, or coverage gap", "verifierStatus")
                )
            if status == "BLOCKED" and not (instance["coverage_gaps"] or instance["requested_context"]):
                issues.append(
                    ValidationIssue("$.status", "BLOCKED requires a coverage gap or context request", "verifierStatus")
                )

        elif schema_id == "token-firewall/benchmark-record@0.1":
            actual_hash = canonical_sha256(instance)
            if instance.get("content_sha256") != actual_hash:
                issues.append(
                    ValidationIssue(
                        "$.content_sha256",
                        f"does not match canonical object content; expected {actual_hash}",
                        "contentHash",
                    )
                )

        elif schema_id == "token-firewall/event@0.1":
            has_ref = "payload_ref" in instance
            has_hash = "payload_sha256" in instance
            if has_ref != has_hash:
                issues.append(ValidationIssue("$", "payload_ref and payload_sha256 must appear together", "evidenceRef"))

        elif schema_id == "token-firewall/external-observability-policy@0.1":
            if instance["stalled_after_seconds"] <= instance["heartbeat_seconds"]:
                issues.append(
                    ValidationIssue(
                        "$.stalled_after_seconds",
                        "must be greater than heartbeat_seconds",
                        "observabilityWindow",
                    )
                )
            if instance["privacy"]["record_chain_of_thought"]:
                issues.append(
                    ValidationIssue(
                        "$.privacy.record_chain_of_thought",
                        "chain-of-thought collection is forbidden",
                        "privacy",
                    )
                )

        elif schema_id == "token-firewall/external-run-event@0.1":
            has_ref = "payload_ref" in instance
            has_hash = "payload_sha256" in instance
            if has_ref != has_hash:
                issues.append(ValidationIssue("$", "payload_ref and payload_sha256 must appear together", "evidenceRef"))
            if instance["kind"] == "run.usage_updated" and "usage" not in instance:
                issues.append(ValidationIssue("$.usage", "usage_updated requires usage", "eventPayload"))
            if instance["kind"] != "run.usage_updated" and "usage" in instance:
                issues.append(ValidationIssue("$.usage", "usage is only valid on usage_updated", "eventPayload"))
            if instance["kind"] in {"run.snapshot_frozen", "run.completed"} and instance["session_id"] is None:
                issues.append(ValidationIssue("$.session_id", "terminal delivery events require session_id", "eventIdentity"))

        elif schema_id == "token-firewall/evaluation-protocol@0.1":
            if instance["control_arm"]["arm_id"] == instance["experiment_arm"]["arm_id"]:
                issues.append(ValidationIssue("$.experiment_arm.arm_id", "arm ids must differ", "experimentDesign"))
            for key, enabled in instance["blinding"].items():
                if not enabled:
                    issues.append(ValidationIssue(f"$.blinding.{key}", "must be enabled", "experimentDesign"))
            if not instance["accounting"]["include_failures"] or not instance["accounting"]["include_rework"]:
                issues.append(ValidationIssue("$.accounting", "failures and rework must be included", "costAccounting"))

        elif schema_id == "token-firewall/evaluation-pair@0.1":
            if instance["control"]["arm_id"] == instance["experiment"]["arm_id"]:
                issues.append(ValidationIssue("$.experiment.arm_id", "paired arm ids must differ", "experimentDesign"))
            provenance = instance["provenance"]
            expected_count = 1 if provenance["campaign_mode"] == "single" else 2
            if len(provenance["experiment_record_sha256"]) < expected_count:
                issues.append(
                    ValidationIssue(
                        "$.provenance.experiment_record_sha256",
                        f"{provenance['campaign_mode']} campaign requires at least {expected_count} experiment records",
                        "provenance",
                    )
                )
            if provenance["control_record_sha256"] in provenance["experiment_record_sha256"]:
                issues.append(ValidationIssue("$.provenance", "control and experiment sources must differ", "provenance"))

        elif schema_id == "token-firewall/evaluation-lab-manifest@0.1":
            pair_ids = [item["pair_id"] for item in instance["pairs"]]
            paths = [item["path"] for item in instance["pairs"]]
            hashes = [item["sha256"] for item in instance["pairs"]]
            if self._duplicates(pair_ids) or self._duplicates(paths) or self._duplicates(hashes):
                issues.append(ValidationIssue("$.pairs", "pair ids, paths, and hashes must be unique", "unique"))
            expected = canonical_sha256(hashes, exclude_content_hash=False)
            if instance["dataset_sha256"] != expected:
                issues.append(
                    ValidationIssue("$.dataset_sha256", f"does not match ordered pair hashes; expected {expected}", "contentHash")
                )

        elif schema_id == "token-firewall/risk-token-budget-policy@0.1":
            tiers = instance["tiers"]
            for name, tier in tiers.items():
                if tier["planning_sol_max"] + tier["review_sol_max"] > tier["total_sol_max"]:
                    issues.append(ValidationIssue(f"$.tiers.{name}.total_sol_max", "must cover planning plus review maxima", "budget"))
            ordered = [tiers[name]["total_sol_max"] for name in ("low", "medium", "high", "critical")]
            if ordered != sorted(ordered):
                issues.append(ValidationIssue("$.tiers", "total Sol budgets must be nondecreasing with risk", "budget"))
            savings = [tiers[name]["minimum_sol_savings_percent"] for name in ("low", "medium", "high", "critical")]
            if savings != sorted(savings, reverse=True):
                issues.append(ValidationIssue("$.tiers", "minimum savings targets must be nonincreasing with risk", "budget"))

        return issues

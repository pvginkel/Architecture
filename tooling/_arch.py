"""Shared schema-load / registry-build / validator machinery.

Imported by both `validate.py` (per-artifact CLI) and `collect.py` (federation
collector). Pure data + pure functions — no printing, no exit-code logic, no
CLI concerns. Callers shape user-facing output.
"""

from __future__ import annotations

import datetime as dt
import re
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import jsonschema
import yaml
from jsonschema import Draft202012Validator
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

UUID4_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)

REPO_ROOT = Path(__file__).resolve().parent.parent
SCHEMA_DIR = REPO_ROOT / "schema" / "v0.1"
GENERATED_DIR = SCHEMA_DIR / "generated"
ENUMS_DIR = SCHEMA_DIR / "enums"
PIPELINE_PRODUCERS_FILE = REPO_ROOT / "pipeline-producers.yaml"
PIPELINE_PRODUCERS_SCHEMA = REPO_ROOT / "pipeline-producers.schema.yaml"


def normalize(obj: Any) -> Any:
    """Convert YAML-parsed date/datetime into ISO strings so JSON Schema
    `format: date` / `format: date-time` validates them as strings.
    """
    if isinstance(obj, dt.datetime):
        return obj.isoformat()
    if isinstance(obj, dt.date):
        return obj.isoformat()
    if isinstance(obj, dict):
        return {k: normalize(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [normalize(v) for v in obj]
    return obj


def load_yaml(path: Path) -> Any:
    with path.open() as fh:
        return yaml.safe_load(fh)


def collect_schema_files() -> list[Path]:
    """Every YAML schema we expect to be a JSON Schema 2020-12 document."""
    files: list[Path] = []
    files.append(SCHEMA_DIR / "architecture.schema.yaml")
    files.append(SCHEMA_DIR / "subset.schema.yaml")
    files.extend(sorted(GENERATED_DIR.glob("*.yaml")))
    return [p for p in files if p.exists()]


def meta_validate_schemas() -> list[tuple[Path, str | None]]:
    """Meta-validate every schema. Returns one result per file; the second
    slot is None for OK, the error message for FAIL. No printing — callers
    shape user-facing output.
    """
    results: list[tuple[Path, str | None]] = []
    for path in collect_schema_files():
        doc = load_yaml(path)
        try:
            Draft202012Validator.check_schema(doc)
            results.append((path, None))
        except jsonschema.SchemaError as e:
            results.append((path, e.message))
    return results


def load_master_schema() -> dict:
    """The architecture.schema.yaml document — root of artifact validation."""
    return load_yaml(SCHEMA_DIR / "architecture.schema.yaml")


def build_registry() -> Registry:
    """Resolve $ref pointers in architecture.schema.yaml against the local
    generated/ tree. Each generated file is registered under both an
    absolute URI (its $id) and a relative file URI (./generated/x.yaml)
    so that whichever form architecture.schema.yaml uses in $ref resolves.
    """
    registry: Registry = Registry()
    arch_path = SCHEMA_DIR / "architecture.schema.yaml"
    arch_uri = arch_path.as_uri()

    for path in sorted(GENERATED_DIR.glob("*.yaml")):
        doc = load_yaml(path)
        resource = Resource(contents=doc, specification=DRAFT202012)
        registry = registry.with_resource(uri=doc["$id"], resource=resource)
        registry = registry.with_resource(uri=path.as_uri(), resource=resource)
        relative_resolved = urljoin(arch_uri, f"./generated/{path.name}")
        registry = registry.with_resource(uri=relative_resolved, resource=resource)
    return registry


def validate_doc(doc: Any) -> list[jsonschema.ValidationError]:
    """Validate one already-parsed-and-normalized artifact against the master
    schema. Returns errors sorted by absolute_path. No I/O, no printing.
    """
    schema_doc = load_master_schema()
    registry = build_registry()
    validator = Draft202012Validator(schema=schema_doc, registry=registry)
    return sorted(validator.iter_errors(doc), key=lambda e: list(e.absolute_path))


def load_capability_enum() -> set[str]:
    """Set of capability ids declared in enums/capabilities.yaml."""
    doc = load_yaml(ENUMS_DIR / "capabilities.yaml")
    return {entry["id"] for entry in doc["entries"]}


def parse_id(s: str) -> tuple[str, str | None, str | None]:
    """Split a v0.1 element id into (kind, hint, uuid). Each component
    may be present or None depending on which of the three forms the
    string takes:

    * composite — ``<kind>:<hint>,<uuid4>``      (declarations of instance kinds)
    * uuid-only — ``<kind>:<uuid4>``             (external reference)
    * hint-only — ``<kind>:<hint>``              (internal reference / catalog
                                                  / curated kind)

    The split is purely syntactic — the function does not enforce which
    form is legal in which position. Callers (per-artifact schema regex,
    collector resolution rules) layer that on top.

    Example:
        parse_id("node:prd-cluster,7f3a2b1c-9d4a-4e8c-b2f1-1a2b3c4d5e6f")
            -> ("node", "prd-cluster", "7f3a2b1c-9d4a-4e8c-b2f1-1a2b3c4d5e6f")
        parse_id("cap:iam")
            -> ("cap", "iam", None)
        parse_id("node:7f3a2b1c-9d4a-4e8c-b2f1-1a2b3c4d5e6f")
            -> ("node", None, "7f3a2b1c-9d4a-4e8c-b2f1-1a2b3c4d5e6f")
    """
    kind, sep, rest = s.partition(":")
    if not sep:
        raise ValueError(f"id {s!r}: missing ':' separator")
    if "," in rest:
        hint, _, uuid_str = rest.partition(",")
        return kind, hint or None, uuid_str or None
    if UUID4_RE.match(rest):
        return kind, None, rest
    return kind, rest, None


def load_pipeline_producers(
    yaml_path: Path = PIPELINE_PRODUCERS_FILE,
    schema_path: Path = PIPELINE_PRODUCERS_SCHEMA,
) -> list[dict]:
    """Load and validate the producer registry. Returns the list of entries
    (each a dict with `id`, `profile`, `jenkinsJob`). Raises ValueError on
    schema violation or duplicate id — fail fast at collector startup, no
    partial recovery.
    """
    schema = load_yaml(schema_path)
    doc = load_yaml(yaml_path)
    Draft202012Validator.check_schema(schema)
    errors = sorted(
        Draft202012Validator(schema).iter_errors(doc),
        key=lambda e: list(e.absolute_path),
    )
    if errors:
        rel = yaml_path.relative_to(REPO_ROOT) if yaml_path.is_relative_to(REPO_ROOT) else yaml_path
        lines = [f"{rel}: {len(errors)} schema error(s):"]
        for e in errors:
            pointer = "/" + "/".join(str(p) for p in e.absolute_path)
            lines.append(f"  at {pointer}: {e.message}")
        raise ValueError("\n".join(lines))

    producers = doc["producers"]
    seen: dict[str, int] = {}
    for i, p in enumerate(producers):
        if p["id"] in seen:
            rel = (
                yaml_path.relative_to(REPO_ROOT)
                if yaml_path.is_relative_to(REPO_ROOT)
                else yaml_path
            )
            raise ValueError(
                f"{rel}: duplicate producer id "
                f"{p['id']!r} at indexes {seen[p['id']]} and {i}"
            )
        seen[p["id"]] = i
    return producers


def load_allowed_triples() -> set[tuple[str, str, str]]:
    """Set of (source-kind, relation-type, target-kind) triples permitted by
    the ArchiMate matrix, narrowed to the v0.1 subset. Read from
    generated/relations.schema.yaml's `x-allowedTriples` array.
    """
    doc = load_yaml(GENERATED_DIR / "relations.schema.yaml")
    return {
        (entry["source"], entry["type"], entry["target"])
        for entry in doc["x-allowedTriples"]
    }

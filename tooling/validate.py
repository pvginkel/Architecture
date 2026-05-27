"""Validate architecture artifacts and meta-validate every v0.1 schema.

Two modes:

    poetry run python validate.py meta
        Walk every YAML schema file under schema/v0.1/ and meta-validate
        against JSON Schema 2020-12. Catches structural mistakes in the
        schemas themselves. Used by the validation service at boot.

    poetry run python validate.py <artifact.yaml>
        Validate one architecture artifact against
        schema/v0.1/architecture.schema.yaml (which $refs the generated
        per-kind schemas). Honors `# expect: <jsonpointer>` headers in
        the file: if the header is present, validation must fail with
        the named pointer in the error path.

Exit codes: 0 on success, 1 on validation failure.
"""

from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path
from typing import Any

import click
import jsonschema
import yaml
from jsonschema import Draft202012Validator
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012


def _normalize(obj: Any) -> Any:
    """Convert YAML-parsed date/datetime into ISO strings so JSON Schema
    `format: date` / `format: date-time` validates them as strings.
    """
    if isinstance(obj, dt.datetime):
        return obj.isoformat()
    if isinstance(obj, dt.date):
        return obj.isoformat()
    if isinstance(obj, dict):
        return {k: _normalize(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_normalize(v) for v in obj]
    return obj

REPO_ROOT = Path(__file__).resolve().parent.parent
SCHEMA_DIR = REPO_ROOT / "schema" / "v0.1"
GENERATED_DIR = SCHEMA_DIR / "generated"
ENUMS_DIR = SCHEMA_DIR / "enums"


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


def meta_validate() -> int:
    """Meta-validate every schema. Returns process exit code."""
    failures = 0
    for path in collect_schema_files():
        doc = load_yaml(path)
        rel = path.relative_to(REPO_ROOT)
        try:
            Draft202012Validator.check_schema(doc)
            click.echo(f"OK   {rel}")
        except jsonschema.SchemaError as e:
            click.echo(f"FAIL {rel}: {e.message}", err=True)
            failures += 1
    return 1 if failures else 0


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
        # Register under the absolute $id from the schema document
        registry = registry.with_resource(uri=doc["$id"], resource=resource)
        # Also register under the file URI (resolved relative to architecture.schema.yaml)
        rel_target = path.as_uri()
        registry = registry.with_resource(uri=rel_target, resource=resource)
        # And under the relative form architecture.schema.yaml uses
        # (./generated/<filename>) — resolve against arch_uri as base.
        from urllib.parse import urljoin

        relative_resolved = urljoin(arch_uri, f"./generated/{path.name}")
        registry = registry.with_resource(uri=relative_resolved, resource=resource)
    return registry


def parse_expected_pointer(artifact_path: Path) -> str | None:
    """Look for `# expect: <pointer>` in the artifact file's header."""
    for line in artifact_path.read_text().splitlines()[:20]:
        line = line.strip()
        if not line.startswith("#"):
            if line:
                break
            continue
        marker = "expect:"
        if marker in line:
            return line.split(marker, 1)[1].strip()
    return None


def validate_artifact(artifact_path: Path) -> int:
    """Validate a single artifact. Returns process exit code."""
    schema_doc = load_yaml(SCHEMA_DIR / "architecture.schema.yaml")
    registry = build_registry()
    artifact = _normalize(load_yaml(artifact_path))

    validator = Draft202012Validator(schema=schema_doc, registry=registry)
    errors = sorted(validator.iter_errors(artifact), key=lambda e: list(e.absolute_path))

    expected = parse_expected_pointer(artifact_path)
    abs_path = artifact_path.resolve()
    try:
        rel = abs_path.relative_to(REPO_ROOT)
    except ValueError:
        rel = abs_path

    if expected is None:
        # File is expected to be valid.
        if errors:
            click.echo(f"FAIL {rel}: expected valid, got {len(errors)} error(s):", err=True)
            for e in errors:
                pointer = "/" + "/".join(str(p) for p in e.absolute_path)
                click.echo(f"  at {pointer}: {e.message}", err=True)
            return 1
        click.echo(f"OK   {rel}: valid")
        return 0

    # File is expected to fail with `expected` in some error's pointer path.
    if not errors:
        click.echo(
            f"FAIL {rel}: expected failure at {expected}, but validation passed.", err=True
        )
        return 1

    matched = False
    for e in errors:
        pointer = "/" + "/".join(str(p) for p in e.absolute_path)
        if expected in pointer:
            matched = True
            click.echo(f"OK   {rel}: failed at {pointer} (expected {expected})")
            break
    if not matched:
        click.echo(
            f"FAIL {rel}: expected failure at {expected}, but actual error(s) were at:",
            err=True,
        )
        for e in errors:
            pointer = "/" + "/".join(str(p) for p in e.absolute_path)
            click.echo(f"  {pointer}: {e.message}", err=True)
        return 1
    return 0


@click.command()
@click.argument("target", required=True)
def main(target: str) -> None:
    """TARGET is either 'meta' (meta-validate schemas) or a path/glob to artifact(s)."""
    if target == "meta":
        sys.exit(meta_validate())

    # Path or glob — supports `validate.py 'schema/v0.1/examples/*.yaml'`.
    paths: list[Path] = []
    if "*" in target or "?" in target:
        from glob import glob

        for p in sorted(glob(target)):
            paths.append(Path(p))
    else:
        paths.append(Path(target))

    if not paths:
        click.echo(f"No files matched {target}", err=True)
        sys.exit(1)

    failures = 0
    for p in paths:
        if not p.exists():
            click.echo(f"FAIL {p}: not found", err=True)
            failures += 1
            continue
        failures += validate_artifact(p)
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()

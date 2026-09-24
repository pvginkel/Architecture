"""Validate architecture artifacts and views, and meta-validate every v0.1 schema.

Three modes:

    poetry run python validate.py meta
        Walk every YAML schema file under schema/v0.1/ and meta-validate
        against JSON Schema 2020-12. Catches structural mistakes in the
        schemas themselves. Used by the validation service at boot.

    poetry run python validate.py views
        Load the repo's views/ the way the collector does (views.schema.yaml
        plus the _order.yaml permutation check), so a broken view fails
        before the push instead of in the central build.

    poetry run python validate.py <artifact.yaml>
        Validate one architecture artifact against
        schema/v0.1/architecture.schema.yaml (which $refs the generated
        per-kind schemas). Honors `# expect: <jsonpointer>` headers in
        the file: if the header is present, validation must fail with
        the named pointer in the error path.

Exit codes: 0 on success, 1 on validation failure.
"""

from __future__ import annotations

import sys
from pathlib import Path

import click

from _arch import (
    REPO_ROOT,
    VIEWS_DIR,
    load_yaml,
    meta_validate_schemas,
    normalize,
    validate_doc,
)
from collect import CollectorError, load_views


def meta_validate() -> int:
    """Meta-validate every schema. Returns process exit code."""
    failures = 0
    for path, error in meta_validate_schemas():
        rel = path.relative_to(REPO_ROOT)
        if error is None:
            click.echo(f"OK   {rel}")
        else:
            click.echo(f"FAIL {rel}: {error}", err=True)
            failures += 1
    return 1 if failures else 0


def views_validate(views_dir: Path) -> int:
    """Load the authored views under `views_dir`. Returns process exit code."""
    try:
        views = load_views(views_dir)
    except CollectorError as e:
        click.echo(f"FAIL [{e.phase}] {len(e.messages)} error(s):", err=True)
        for m in e.messages:
            click.echo(f"  {m}", err=True)
        return 1
    click.echo(f"OK   {views_dir}: {len(views)} view(s)")
    return 0


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
    artifact = normalize(load_yaml(artifact_path))
    errors = validate_doc(artifact)

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
    """TARGET is 'meta' (meta-validate schemas), 'views' (load the repo's views/) or a
    path/glob to artifact(s)."""
    if target == "meta":
        sys.exit(meta_validate())
    if target == "views":
        sys.exit(views_validate(VIEWS_DIR))

    # Path or glob — supports `validate.py 'schema/v0.1/examples/*.yaml'`.
    paths: list[Path] = []
    if "*" in target or "?" in target:
        from glob import glob

        for match in sorted(glob(target)):
            paths.append(Path(match))
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

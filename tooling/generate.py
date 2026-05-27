"""Generate per-kind JSON Schemas from the vendored ArchiMate XSD,
the Archi 3.2 relationship matrix, and schema/v0.1/subset.yaml.

Outputs are written to schema/v0.1/generated/. The script is idempotent;
CI re-runs it and gates on a clean diff.

Run with:

    poetry run python tooling/generate.py

or, from the tooling directory:

    poetry run python generate.py
"""

from __future__ import annotations

import re
import sys
import xml.etree.ElementTree as ET
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import click
import jsonschema
import xmlschema
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
SCHEMA_DIR = REPO_ROOT / "schema" / "v0.1"
ARCHIMATE_DIR = SCHEMA_DIR / "archimate"
GENERATED_DIR = SCHEMA_DIR / "generated"

SUBSET_PATH = SCHEMA_DIR / "subset.yaml"
SUBSET_SCHEMA_PATH = SCHEMA_DIR / "subset.schema.yaml"
XSD_PATH = ARCHIMATE_DIR / "archimate3_Model.xsd"
RELATIONSHIPS_PATH = ARCHIMATE_DIR / "relationships.xml"
RELATIONSHIPS_KEYS_PATH = ARCHIMATE_DIR / "relationships-keys.xml"

LIFECYCLE_VALUES = ("active", "deprecated", "removed")
ENVIRONMENT_VALUES = ("dev", "tst", "uat", "prd")
SCHEMA_BASE_URL = "https://architecture.webathome.org/schema/v0.1"
JSON_SCHEMA_DRAFT = "https://json-schema.org/draft/2020-12/schema"

UUID4_PATTERN = "[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}"


def load_yaml(path: Path) -> Any:
    with path.open() as fh:
        return yaml.safe_load(fh)


def dump_yaml(data: Any, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as fh:
        yaml.safe_dump(data, fh, sort_keys=False, width=120)


def extract_xsd_enums(xsd_path: Path) -> tuple[set[str], set[str]]:
    """Return (element_type_names, relationship_type_names) from the XSD.

    The XSD encodes both as `xsi:type` discriminators inside abstract
    ElementType / RelationshipType complex types. We pull both by examining
    the concrete complexType definitions and partitioning by which abstract
    base they extend.
    """
    schema = xmlschema.XMLSchema(str(xsd_path))
    element_types: set[str] = set()
    relationship_types: set[str] = set()

    # Walk all global complex types and partition by their base hierarchy.
    for name, ct in schema.types.items():
        if not name or "ArchiMate" in name:
            continue
        # Find base type chain
        bases: list[str] = []
        node = ct
        while node is not None:
            base = getattr(node, "base_type", None)
            if base is None or base.name is None:
                break
            bases.append(base.local_name or base.name)
            if base is node:
                break
            node = base
        if "ElementType" in bases or "RealElementType" in bases:
            element_types.add(name)
        if "RelationshipType" in bases or "RelationshipConnectorType" in bases:
            relationship_types.add(name)

    return element_types, relationship_types


def load_relationship_matrix(
    matrix_path: Path, keys_path: Path
) -> tuple[dict[str, str], dict[tuple[str, str], set[str]]]:
    """Return (key_letter → relationship-name, (source, target) → set of names).

    Source and target names are ArchiMate concept names (e.g. "ApplicationComponent").
    Relationship names come from relationships-keys.xml, with the
    "Relationship" suffix stripped to match the XSD enumeration form.
    """
    key_tree = ET.parse(keys_path)
    key_root = key_tree.getroot()
    key_to_name: dict[str, str] = {}
    for k in key_root.findall("key"):
        char = k.attrib["char"]
        rel = k.attrib["relationship"]
        # Strip trailing "Relationship" to match XSD enum form (e.g. Access).
        if rel.endswith("Relationship"):
            rel = rel[: -len("Relationship")]
        key_to_name[char] = rel

    matrix_tree = ET.parse(matrix_path)
    matrix_root = matrix_tree.getroot()
    triples: dict[tuple[str, str], set[str]] = {}
    for source in matrix_root.findall("source"):
        src_concept = source.attrib["concept"]
        for target in source.findall("target"):
            tgt_concept = target.attrib["concept"]
            rels = target.attrib.get("relations", "")
            triples[(src_concept, tgt_concept)] = {key_to_name[c] for c in rels if c in key_to_name}
    return key_to_name, triples


def validate_subset_structure(subset: Mapping[str, Any], subset_schema: Mapping[str, Any]) -> None:
    jsonschema.validate(instance=subset, schema=subset_schema)


def validate_subset_against_xsd(
    subset: Mapping[str, Any], xsd_element_types: set[str]
) -> list[str]:
    """Return list of error messages. Empty list means OK."""
    errors: list[str] = []
    reserved = set(subset["xsdReservedAttributeNames"])

    # 1. Every kind's archimateType exists in the XSD.
    for kind_name, kind in subset["kinds"].items():
        atype = kind["archimateType"]
        if atype not in xsd_element_types:
            errors.append(
                f"kinds.{kind_name}.archimateType '{atype}' is not a known "
                f"ArchiMate element type (XSD enumeration)."
            )

    # 2. No custom attribute name collides with an XSD-reserved name.
    common = subset.get("commonAttributes", {})
    for attr_name in common:
        if attr_name in reserved:
            errors.append(
                f"commonAttributes.{attr_name} collides with an XSD-reserved attribute name."
            )

    for kind_name, kind in subset["kinds"].items():
        for attr_name in kind.get("attributesAddition", {}):
            if attr_name in reserved:
                errors.append(
                    f"kinds.{kind_name}.attributesAddition.{attr_name} collides "
                    f"with an XSD-reserved attribute name."
                )

    for stereo_name, stereo in subset.get("stereotypes", {}).items():
        for attr_name in stereo.get("addedAttributes", {}):
            if attr_name in reserved:
                errors.append(
                    f"stereotypes.{stereo_name}.addedAttributes.{attr_name} collides "
                    f"with an XSD-reserved attribute name."
                )

    # 3. Stereotype appliesTo references kinds that exist.
    kind_names = set(subset["kinds"].keys())
    for stereo_name, stereo in subset.get("stereotypes", {}).items():
        for target_kind in stereo["appliesTo"]:
            if target_kind not in kind_names:
                errors.append(
                    f"stereotypes.{stereo_name}.appliesTo references unknown kind '{target_kind}'."
                )
        for required_stereo in stereo.get("requires", []):
            if required_stereo not in subset["stereotypes"]:
                errors.append(
                    f"stereotypes.{stereo_name}.requires references unknown "
                    f"stereotype '{required_stereo}'."
                )

    return errors


# ---------- per-kind schema emission ----------


def attribute_to_json_schema(
    attr_name: str, spec: Mapping[str, Any], kind_id_regex: str
) -> dict[str, Any]:
    """Translate a subset.yaml attributeSpec into a JSON Schema property."""
    t = spec["type"]
    out: dict[str, Any] = {"description": spec["description"]}

    if t == "string":
        out["type"] = "string"
        out["minLength"] = 1
    elif t == "date":
        out["type"] = "string"
        out["format"] = "date"
    elif t == "uri":
        out["type"] = "string"
        out["format"] = "uri"
    elif t == "enum":
        out["type"] = "string"
        if "enumValues" in spec:
            out["enum"] = list(spec["enumValues"])
        else:
            # enumRef — we expand the values inline so the generated schema
            # is self-contained. The generator resolves the reference once.
            out["enum"] = resolve_enum_ref(spec["enumRef"])
    elif t == "idRef":
        out["type"] = "string"
        # We don't enforce the exact target regex on a ref — the collector
        # does cross-element existence checks at merge time. We do enforce
        # prefix via a simple pattern.
        kind = spec["refKind"]
        prefix = kind_prefix(kind)
        out["pattern"] = f"^{re.escape(prefix)}"
    elif t == "stringMap":
        out["type"] = "object"
        out["additionalProperties"] = {"type": "string"}
    else:
        raise ValueError(f"Unknown attribute type '{t}' for attribute '{attr_name}'")

    return out


_KIND_PREFIX_OVERRIDE: dict[str, str] = {}


def kind_prefix(kind_name: str) -> str:
    return _KIND_PREFIX_OVERRIDE.get(kind_name, "")


def resolve_enum_ref(rel_path: str) -> list[str]:
    """Resolve enumRef to a list of id values from an enum file."""
    abs_path = (SCHEMA_DIR / rel_path).resolve()
    if not abs_path.exists():
        # During first generation, enum files may not yet exist. Permit
        # the reference to remain symbolic in that case — but keep the
        # generator deterministic. We emit a placeholder list with the
        # known values for built-in enums; otherwise raise.
        name = abs_path.name
        if name == "lifecycle-states.yaml":
            return list(LIFECYCLE_VALUES)
        if name == "environments.yaml":
            return list(ENVIRONMENT_VALUES)
        raise FileNotFoundError(
            f"enumRef {rel_path} not found and no built-in fallback available. "
            f"Author the enum file first or pre-load fallback values."
        )
    data = load_yaml(abs_path)
    return [entry["id"] for entry in data["entries"]]


def emit_per_kind_schema(
    kind_name: str,
    kind: Mapping[str, Any],
    common: Mapping[str, Any],
    stereotypes: Mapping[str, Any],
) -> dict[str, Any]:
    """Build a JSON Schema for one element kind."""
    properties: dict[str, dict[str, Any]] = {}
    required: list[str] = []
    id_regex = kind["idRegex"]

    # 1. id field — kind-specific pattern.
    properties["id"] = {
        "type": "string",
        "pattern": id_regex,
        "description": common["id"]["description"],
    }
    required.append("id")

    # 2. Common attributes (excluding `id`, handled above).
    for attr_name, spec in common.items():
        if attr_name == "id":
            continue
        properties[attr_name] = attribute_to_json_schema(attr_name, spec, id_regex)
        if spec.get("required"):
            required.append(attr_name)

    # 3. Kind-specific additional attributes.
    for attr_name, spec in kind.get("attributesAddition", {}).items():
        properties[attr_name] = attribute_to_json_schema(attr_name, spec, id_regex)
        if spec.get("required"):
            required.append(attr_name)

    # 4. Stereotype slot + stereotype-specific attributes (all optional in
    #    base; we add conditional rules below to enforce presence when set).
    applicable = list(kind.get("applicableStereotypes", []))
    stereotype_specific_attrs: dict[str, list[str]] = {}
    if applicable:
        properties["stereotype"] = {
            "type": "string",
            "enum": applicable,
            "description": "Optional stereotype marker.",
        }
        for stereo_name in applicable:
            stereo = stereotypes[stereo_name]
            stereo_attrs: list[str] = []
            for attr_name, spec in stereo.get("addedAttributes", {}).items():
                if attr_name in properties:
                    # Same-named stereotype attrs across multiple applicable
                    # stereotypes share one property declaration.
                    stereo_attrs.append(attr_name)
                    continue
                properties[attr_name] = attribute_to_json_schema(attr_name, spec, id_regex)
                stereo_attrs.append(attr_name)
            stereotype_specific_attrs[stereo_name] = stereo_attrs

    # 5. Conditional rules.
    all_of: list[dict[str, Any]] = []

    # 5a. Per stereotype: when stereotype is set, required stereotype-attrs
    #     must be present. When unset, none of the stereotype-attrs may
    #     appear (they're additionalProperties otherwise).
    for stereo_name, _attrs in stereotype_specific_attrs.items():
        stereo = stereotypes[stereo_name]
        required_stereo_attrs = [
            a for a, s in stereo.get("addedAttributes", {}).items() if s.get("required")
        ]
        if required_stereo_attrs:
            all_of.append(
                {
                    "if": {
                        "properties": {"stereotype": {"const": stereo_name}},
                        "required": ["stereotype"],
                    },
                    "then": {"required": required_stereo_attrs},
                }
            )

    # 5b. When stereotype is unset, no stereotype-specific attrs may appear.
    if stereotype_specific_attrs:
        all_attr_names_across_stereos = sorted(
            {a for attrs in stereotype_specific_attrs.values() for a in attrs}
        )
        if all_attr_names_across_stereos:
            all_of.append(
                {
                    "if": {"not": {"required": ["stereotype"]}},
                    "then": {
                        "allOf": [
                            {"not": {"required": [a]}} for a in all_attr_names_across_stereos
                        ]
                    },
                }
            )

    # Build the schema.
    schema: dict[str, Any] = {
        "$schema": JSON_SCHEMA_DRAFT,
        "$id": f"{SCHEMA_BASE_URL}/generated/{kind_name.lower()}.schema.yaml",
        "title": f"{kind_name} (ArchiMate {kind['archimateType']})",
        "description": kind["description"],
        "type": "object",
        "additionalProperties": False,
        "required": required,
        "properties": properties,
    }
    if all_of:
        schema["allOf"] = all_of

    return schema


def emit_relations_schema(
    relationship_types: set[str],
    matrix: Mapping[tuple[str, str], set[str]],
    subset_kinds: Mapping[str, Any],
) -> dict[str, Any]:
    """Build relations.schema.yaml: allowed (source-kind, type, target-kind) triples."""
    # Map our kind name → its ArchiMate concept name (same in v0.1 — kinds
    # are named after their ArchiMate type — but keep the indirection clean).
    kind_to_concept = {
        kname: k["archimateType"] for kname, k in subset_kinds.items()
    }
    concept_to_kinds: dict[str, list[str]] = {}
    for kname, concept in kind_to_concept.items():
        concept_to_kinds.setdefault(concept, []).append(kname)

    # Narrow the full triple matrix to only entries where both source and
    # target concepts map to a subset-included kind.
    allowed_triples: list[tuple[str, str, str]] = []
    for (src_concept, tgt_concept), rels in matrix.items():
        for src_kind in concept_to_kinds.get(src_concept, []):
            for tgt_kind in concept_to_kinds.get(tgt_concept, []):
                for rel in sorted(rels):
                    allowed_triples.append((src_kind, rel, tgt_kind))

    allowed_triples.sort()

    description = (
        "A relation entry. Each (source, target, type) triple must appear "
        "in the x-allowedTriples enumeration below. Source and target are "
        "id references to elements whose source-kind and target-kind "
        "appear in the triple. The validation service performs the kind "
        "lookup at validate time; this schema only constrains type names "
        "and structural shape."
    )

    return {
        "$schema": JSON_SCHEMA_DRAFT,
        "$id": f"{SCHEMA_BASE_URL}/generated/relations.schema.yaml",
        "title": "Relations (ArchiMate 3.2 triple matrix, narrowed to v0.1 subset)",
        "description": description,
        "type": "object",
        "additionalProperties": False,
        "required": ["id", "source", "target", "type"],
        "properties": {
            "id": {
                "type": "string",
                "pattern": "^rel:[a-z][a-z0-9-]*$|^rel:" + UUID4_PATTERN + "$",
                "description": "Stable identifier for this relation.",
            },
            "source": {"type": "string", "description": "Source element id."},
            "target": {"type": "string", "description": "Target element id."},
            "type": {
                "type": "string",
                "enum": sorted(relationship_types),
                "description": "ArchiMate relationship type.",
            },
        },
        # The allowed-triples enumeration is a derived artifact; embed it
        # so the validation service can enforce it without re-deriving.
        "x-allowedTriples": [
            {"source": s, "type": t, "target": tg} for (s, t, tg) in allowed_triples
        ],
    }


# ---------- driver ----------


@click.command()
@click.option(
    "--check",
    is_flag=True,
    help="Check generated/ is up to date; exit non-zero if regeneration would change anything.",
)
def main(check: bool) -> None:
    subset = load_yaml(SUBSET_PATH)
    subset_schema = load_yaml(SUBSET_SCHEMA_PATH)

    click.echo(f"Loading XSD from {XSD_PATH.relative_to(REPO_ROOT)}")
    xsd_element_types, xsd_relationship_types = extract_xsd_enums(XSD_PATH)
    click.echo(
        f"  {len(xsd_element_types)} element types, "
        f"{len(xsd_relationship_types)} relationship types"
    )

    click.echo(f"Loading relationship matrix from {RELATIONSHIPS_PATH.relative_to(REPO_ROOT)}")
    _keys, triple_matrix = load_relationship_matrix(RELATIONSHIPS_PATH, RELATIONSHIPS_KEYS_PATH)
    click.echo(f"  {len(triple_matrix)} (source, target) concept pairs")

    click.echo("Validating subset.yaml structure")
    validate_subset_structure(subset, subset_schema)

    click.echo("Validating subset.yaml against XSD-derived metadata")
    errors = validate_subset_against_xsd(subset, xsd_element_types)
    if errors:
        click.echo("ERRORS:", err=True)
        for err in errors:
            click.echo(f"  - {err}", err=True)
        sys.exit(1)
    click.echo("  OK")

    # Populate prefix lookup for idRef resolution.
    for kind_name, kind in subset["kinds"].items():
        _KIND_PREFIX_OVERRIDE[kind_name] = kind["idPrefix"]

    # Per-kind schemas.
    new_files: dict[Path, str] = {}
    for kind_name, kind in subset["kinds"].items():
        schema_doc = emit_per_kind_schema(
            kind_name, kind, subset["commonAttributes"], subset["stereotypes"]
        )
        path = GENERATED_DIR / f"{kind_name.lower()}.schema.yaml"
        new_files[path] = yaml.safe_dump(schema_doc, sort_keys=False, width=120)

    # Relations schema.
    rel_doc = emit_relations_schema(xsd_relationship_types, triple_matrix, subset["kinds"])
    new_files[GENERATED_DIR / "relations.schema.yaml"] = yaml.safe_dump(
        rel_doc, sort_keys=False, width=120
    )

    # Write or check.
    if check:
        drift = False
        for path, content in new_files.items():
            existing = path.read_text() if path.exists() else None
            if existing != content:
                click.echo(f"DRIFT: {path.relative_to(REPO_ROOT)}", err=True)
                drift = True
        # Detect files in generated/ that we no longer emit.
        if GENERATED_DIR.exists():
            for orphan in GENERATED_DIR.iterdir():
                if orphan not in new_files:
                    click.echo(f"ORPHAN: {orphan.relative_to(REPO_ROOT)}", err=True)
                    drift = True
        if drift:
            sys.exit(1)
        click.echo("generated/ is up to date.")
    else:
        GENERATED_DIR.mkdir(parents=True, exist_ok=True)
        for path, content in new_files.items():
            path.write_text(content)
        # Remove orphans.
        for orphan in GENERATED_DIR.iterdir():
            if orphan not in new_files:
                click.echo(f"Removing orphan: {orphan.relative_to(REPO_ROOT)}")
                orphan.unlink()
        click.echo(f"Wrote {len(new_files)} files to {GENERATED_DIR.relative_to(REPO_ROOT)}.")


if __name__ == "__main__":
    main()

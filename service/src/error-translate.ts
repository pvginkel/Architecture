import type { ErrorObject } from "ajv";

export interface TranslatedError {
  /** JSON Pointer into the submitted artifact. */
  path: string;
  /** Full-sentence English explanation, quoting the offending value when short. */
  message: string;
  /** The value at `path` (extracted from the artifact), so the reader doesn't have to re-fetch it. */
  value?: unknown;
  /** Machine-readable error class (`enum`, `pattern`, `required`, …). */
  keyword: string;
  /** The most specific schema or enum file relevant to the error. */
  schemaUrl: string;
  /** One-line next-step suggestion. Optional. */
  hint?: string;
}

const SCHEMA_BASE = "https://architecture.webathome.org/schema/v0.1";
const ENVELOPE_URL = `${SCHEMA_BASE}/architecture.schema.json`;

/** Envelope-property → generated kind schema file (canonical .json form). */
const KIND_BY_TOP_PROPERTY: Record<string, string> = {
  nodes: "generated/node.schema.json",
  devices: "generated/device.schema.json",
  systemSoftware: "generated/systemsoftware.schema.json",
  applicationComponents: "generated/applicationcomponent.schema.json",
  applicationServices: "generated/applicationservice.schema.json",
  applicationInterfaces: "generated/applicationinterface.schema.json",
  technologyServices: "generated/technologyservice.schema.json",
  technologyInterfaces: "generated/technologyinterface.schema.json",
  artifacts: "generated/artifact.schema.json",
  capabilities: "generated/capability.schema.json",
  businessServices: "generated/businessservice.schema.json",
  groupings: "generated/grouping.schema.json",
  relations: "generated/relations.schema.json",
};

/** id-prefix → enum file (for hinting on enum-style validation failures). */
const ENUM_FILE_BY_ID_PREFIX: Record<string, string> = {
  "cap:": "enums/capabilities.json",
};

/** Keywords that signal a conditional/structural failure — these should be
 *  collapsed to a single error per instancePath when leaf errors are absent. */
const STRUCTURAL_KEYWORDS = new Set([
  "if",
  "then",
  "else",
  "oneOf",
  "anyOf",
  "allOf",
  "not",
]);

/**
 * Translate raw ajv errors into the LLM-friendly shape and deduplicate
 * oneOf/if-then cascades so the caller sees one entry per real problem.
 */
export function translateErrors(
  rawErrors: readonly ErrorObject[],
  artifact: unknown,
): TranslatedError[] {
  if (rawErrors.length === 0) return [];

  const deduped = dedupCascades(rawErrors);
  return deduped.map((e) => translateOne(e, artifact));
}

// Preferred informativeness order for structural cascade summaries.
// Lower number = more informative, picked first.
const STRUCTURAL_PRIORITY: Record<string, number> = {
  not: 0,
  oneOf: 1,
  anyOf: 1,
  if: 2,
  then: 2,
  else: 2,
  allOf: 3,
};

function dedupCascades(errors: readonly ErrorObject[]): ErrorObject[] {
  // Group errors by instancePath. Within each group, structural cascade
  // keywords (oneOf, allOf, not, …) typically have leaf sub-errors emitted
  // from inside their schema sub-tree. Those leaves are noise — keep one
  // canonical structural error for the cascade, and only keep leaf errors
  // that originate outside the cascade's schema sub-tree.
  const byPath = new Map<string, ErrorObject[]>();
  for (const e of errors) {
    const key = e.instancePath ?? "";
    const list = byPath.get(key) ?? [];
    list.push(e);
    byPath.set(key, list);
  }

  const out: ErrorObject[] = [];
  for (const [, group] of byPath) {
    const structurals = group.filter((e) => STRUCTURAL_KEYWORDS.has(e.keyword));
    const leafs = group.filter((e) => !STRUCTURAL_KEYWORDS.has(e.keyword));

    if (structurals.length === 0) {
      pushDedupedLeafs(out, leafs);
      continue;
    }

    // Outermost / most-informative structural is the summary.
    structurals.sort((a, b) => {
      const pa = STRUCTURAL_PRIORITY[a.keyword] ?? 9;
      const pb = STRUCTURAL_PRIORITY[b.keyword] ?? 9;
      if (pa !== pb) return pa - pb;
      return a.schemaPath.length - b.schemaPath.length;
    });
    const summary = structurals[0]!;

    // Leafs nested under any structural's schema sub-tree are cascade noise.
    const subordinatePrefixes = structurals.map((s) => s.schemaPath + "/");
    const independentLeafs = leafs.filter(
      (l) => !subordinatePrefixes.some((p) => l.schemaPath.startsWith(p)),
    );

    out.push(summary);
    pushDedupedLeafs(out, independentLeafs);
  }
  // Stable order: by instancePath, then by schemaPath.
  out.sort((a, b) => {
    if (a.instancePath !== b.instancePath) {
      return a.instancePath < b.instancePath ? -1 : 1;
    }
    return a.schemaPath < b.schemaPath ? -1 : a.schemaPath > b.schemaPath ? 1 : 0;
  });
  return out;
}

function pushDedupedLeafs(out: ErrorObject[], leafs: readonly ErrorObject[]): void {
  const seen = new Set<string>();
  for (const e of leafs) {
    const k = `${e.keyword}|${e.schemaPath}|${JSON.stringify(e.params)}`;
    if (seen.has(k)) continue;
    seen.add(k);
    out.push(e);
  }
}

function translateOne(e: ErrorObject, artifact: unknown): TranslatedError {
  const path = e.instancePath ?? "";
  const value = extractByPointer(artifact, path);
  const fn = translators[e.keyword] ?? translateGeneric;
  const partial = fn(e, value);
  const schemaUrl = partial.schemaUrl ?? deriveSchemaUrl(path, e, value);
  return {
    path,
    keyword: e.keyword,
    message: partial.message,
    schemaUrl,
    ...(value !== undefined ? { value } : {}),
    ...(partial.hint !== undefined ? { hint: partial.hint } : {}),
  };
}

interface PartialTranslation {
  message: string;
  hint?: string;
  schemaUrl?: string;
}

type Translator = (e: ErrorObject, value: unknown) => PartialTranslation;

const translators: Record<string, Translator> = {
  additionalProperties(e, _value): PartialTranslation {
    const prop = (e.params as { additionalProperty?: string }).additionalProperty;
    return {
      message: prop
        ? `unknown property '${prop}' — every element kind sets additionalProperties:false`
        : `unknown property — every element kind sets additionalProperties:false`,
      hint: prop
        ? `remove '${prop}' or PR the field onto the kind schema in subset.yaml`
        : undefined,
    };
  },
  required(e, _value): PartialTranslation {
    const prop = (e.params as { missingProperty?: string }).missingProperty;
    return {
      message: prop
        ? `missing required field '${prop}'`
        : `missing a required field`,
      hint: prop ? `add the '${prop}' field` : undefined,
    };
  },
  type(e, value): PartialTranslation {
    const expected = (e.params as { type?: string | string[] }).type;
    return {
      message: `value ${quoteShort(value)} is not of expected type ${
        Array.isArray(expected) ? expected.join("|") : (expected ?? "?")
      }`,
    };
  },
  enum(e, value): PartialTranslation {
    const allowed = (e.params as { allowedValues?: unknown[] }).allowedValues ?? [];
    const preview = allowed.slice(0, 5).map(quoteShort).join(", ");
    const more = allowed.length > 5 ? `, … (+${allowed.length - 5} more)` : "";
    return {
      message: `value ${quoteShort(value)} is not in the allowed enumeration`,
      hint: allowed.length > 0 ? `allowed: ${preview}${more}` : undefined,
    };
  },
  const(e, value): PartialTranslation {
    const expected = (e.params as { allowedValue?: unknown }).allowedValue;
    return {
      message: `value ${quoteShort(value)} must equal ${quoteShort(expected)}`,
    };
  },
  pattern(e, value): PartialTranslation {
    const pattern = (e.params as { pattern?: string }).pattern;
    return {
      message: `value ${quoteShort(value)} does not match the required pattern${
        pattern ? ` /${pattern}/` : ""
      }`,
      hint: pattern ? `see the schema's pattern for the exact rule` : undefined,
    };
  },
  format(e, value): PartialTranslation {
    const fmt = (e.params as { format?: string }).format;
    return {
      message: `value ${quoteShort(value)} is not a valid ${fmt ?? "format"}`,
    };
  },
  minLength(e, value): PartialTranslation {
    const limit = (e.params as { limit?: number }).limit;
    return {
      message: `string is too short (must be ≥ ${limit ?? "?"} characters): ${quoteShort(value)}`,
    };
  },
  minItems(e, _value): PartialTranslation {
    const limit = (e.params as { limit?: number }).limit;
    return { message: `array must have at least ${limit ?? "?"} item(s)` };
  },
  uniqueItems(e, _value): PartialTranslation {
    const i = (e.params as { i?: number; j?: number }).i;
    const j = (e.params as { i?: number; j?: number }).j;
    return {
      message:
        i !== undefined && j !== undefined
          ? `array items at positions ${j} and ${i} are duplicates`
          : `array contains duplicate items`,
    };
  },
  oneOf(_e, _value): PartialTranslation {
    return {
      message: "value violates a conditional rule (must match exactly one branch of oneOf)",
      hint: "check the schema's lifecycle/conditional rules for the offending field",
    };
  },
  anyOf(_e, _value): PartialTranslation {
    return {
      message: "value does not satisfy any branch of anyOf",
    };
  },
  allOf(_e, _value): PartialTranslation {
    return {
      message: "value violates one or more allOf constraints",
    };
  },
  not(_e, _value): PartialTranslation {
    return {
      message:
        "value satisfies a forbidden constraint (a `not` schema matched when it should not have)",
      hint: "likely a stereotype rule — e.g. stereotype-specific attributes present without the stereotype",
    };
  },
  if(_e, _value): PartialTranslation {
    return {
      message: "conditional rule did not match the 'then' branch",
      hint: "usually a stereotype-conditional rule (stereotype-specific required attributes)",
    };
  },
  then(_e, _value): PartialTranslation {
    return { message: "conditional rule's 'then' branch failed" };
  },
  else(_e, _value): PartialTranslation {
    return { message: "conditional rule's 'else' branch failed" };
  },
};

function translateGeneric(e: ErrorObject, _value: unknown): PartialTranslation {
  return {
    message: e.message ?? `validation failed (${e.keyword})`,
  };
}

function deriveSchemaUrl(path: string, e: ErrorObject, value: unknown): string {
  // Enum-ish failures on a known id prefix point at the enum file.
  if ((e.keyword === "enum" || e.keyword === "pattern") && typeof value === "string") {
    for (const [prefix, file] of Object.entries(ENUM_FILE_BY_ID_PREFIX)) {
      if (value.startsWith(prefix)) return `${SCHEMA_BASE}/${file}`;
    }
  }
  // Path-prefix → kind schema mapping.
  const segs = path.split("/").filter(Boolean);
  if (segs.length > 0) {
    const kindFile = KIND_BY_TOP_PROPERTY[segs[0]!];
    if (kindFile) return `${SCHEMA_BASE}/${kindFile}`;
  }
  return ENVELOPE_URL;
}

function quoteShort(value: unknown): string {
  if (value === undefined) return "(missing)";
  if (value === null) return "null";
  if (typeof value === "string") {
    return value.length <= 60 ? `'${value}'` : `'${value.slice(0, 57)}…'`;
  }
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  return typeof value;
}

/** Resolve a JSON Pointer (RFC 6901) against the artifact. Returns undefined
 *  if any segment is missing. */
export function extractByPointer(artifact: unknown, pointer: string): unknown {
  if (!pointer) return artifact;
  if (!pointer.startsWith("/")) return undefined;
  const segments = pointer
    .slice(1)
    .split("/")
    .map((s) => s.replace(/~1/g, "/").replace(/~0/g, "~"));
  let cur: unknown = artifact;
  for (const seg of segments) {
    if (Array.isArray(cur)) {
      const idx = Number(seg);
      if (!Number.isInteger(idx)) return undefined;
      cur = cur[idx];
    } else if (cur && typeof cur === "object") {
      cur = (cur as Record<string, unknown>)[seg];
    } else {
      return undefined;
    }
    if (cur === undefined) return undefined;
  }
  return cur;
}

import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { parse } from "yaml";
import { buildModel } from "../data/model";
import type { Manifest, ManifestElement, ViewDefinition } from "../data/manifest";
import { ELEMENT_KINDS, KIND_TO_ARRAY } from "../generated/vocab";
import { resolveViewScope } from "./scope";

// The authored Infrastructure view resolved over the self-producer's own files.
// The shared catalog and the rack hardware share the `architecture` producer, so
// no producer gate can tell them apart.

function readRepo<T>(path: string): T {
  return parse(readFileSync(new URL(`../../../${path}`, import.meta.url), "utf8")) as T;
}

type Arrays = Record<string, ManifestElement[]>;

/** One artifact file's elements by manifest array, stamped with the file's
 *  producer the way the collector merges them. */
function readArtifact(path: string): Arrays {
  const doc = readRepo<Record<string, unknown>>(path);
  return Object.fromEntries(
    ELEMENT_KINDS.map((kind) => {
      const key = KIND_TO_ARRAY[kind];
      const elements = (doc[key] ?? []) as ManifestElement[];
      return [key, elements.map((el) => ({ ...el, producer: doc.producer as string }))];
    }),
  );
}

const ids = (arrays: Arrays): string[] =>
  Object.values(arrays)
    .flat()
    .map((el) => el.id);

describe("the Infrastructure view over the self-producer's artifact", () => {
  const catalog = readArtifact("docs/architecture/catalog.yaml");
  const hardware = readArtifact("docs/architecture/infrastructure.yaml");
  const manifest = {
    ...Object.fromEntries(
      Object.keys(catalog).map((key) => [key, [...catalog[key], ...hardware[key]]]),
    ),
    relations: [],
    derived: { capabilityRealizations: {} },
  } as unknown as Manifest;
  const scope = resolveViewScope(
    readRepo<ViewDefinition>("views/infrastructure.yaml"),
    buildModel(manifest),
    manifest,
  );

  it("leaves out the shared catalog's products", () => {
    expect(ids(catalog).filter((id) => scope.has(id))).toEqual([]);
  });

  it("leaves out system software from other producers", () => {
    const release = { id: "ss:grafana-prd-grafana,00000000-0000-5000-8000-000000000000",
      label: "grafana (prd)", producer: "grafana-deploy", environment: "prd" } as ManifestElement;
    const withRelease = {
      ...manifest,
      systemSoftware: [...(manifest.systemSoftware ?? []), release],
    } as Manifest;
    const view = readRepo<ViewDefinition>("views/infrastructure.yaml");
    expect(resolveViewScope(view, buildModel(withRelease), withRelease).has(release.id)).toBe(false);
  });

  it("shows the rack and network hardware", () => {
    expect(ids(hardware).length).toBeGreaterThan(0);
    expect(ids(hardware).filter((id) => !scope.has(id))).toEqual([]);
  });
});

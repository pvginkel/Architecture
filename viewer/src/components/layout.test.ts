import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Edge, Node } from "@xyflow/react";
import type { ElkNode } from "elkjs/lib/elk-api.js";
import { getDirectedLayout, LAYOUT_ABORTED, type ElkFactory, type ElkLike } from "./layout";
import { NODE_WIDTH } from "../data/model";

// FAN_COLUMNS = floor(MAX_ROW_WIDTH / PITCH_X) = floor(6000 / (NODE_WIDTH + 64))
// = floor(6000 / 364) = 16. A row trips discoverWideRowFans only with MORE than
// FAN_COLUMNS members, so we place WIDE_ROW_COUNT = 17 nodes on a single rounded
// Y to force a second pass. (Documented choice: 17 = FAN_COLUMNS + 1, the minimum
// that trips the rule.)
const PITCH_X = NODE_WIDTH + 64;
const WIDE_ROW_COUNT = 17;

// --- Fixtures ----------------------------------------------------------------

/** Architecture nodes with the minimal data bandPartition needs (kind + layer). */
function archNodes(count: number): Node[] {
  return Array.from({ length: count }, (_, i) => ({
    id: `n${i}`,
    type: "architecture",
    position: { x: 0, y: 0 },
    data: { kind: "ApplicationComponent", layer: "application" },
  })) as unknown as Node[];
}

const NO_EDGES: Edge[] = [];

// --- Controllable fake ELK ---------------------------------------------------

interface Deferred<T> {
  promise: Promise<T>;
  resolve: (value: T) => void;
}

function deferred<T>(): Deferred<T> {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((res) => {
    resolve = res;
  });
  return { promise, resolve };
}

/** Build an ElkNode result placing the graph's children at the given positions
 *  (id -> {x,y}); any child not in the map lands at (0,0). */
function resultFor(graph: ElkNode, positions: Map<string, { x: number; y: number }>): ElkNode {
  return {
    ...graph,
    children: (graph.children ?? []).map((child) => ({
      ...child,
      x: positions.get(child.id)?.x ?? 0,
      y: positions.get(child.id)?.y ?? 0,
    })),
  };
}

/** All children spread onto distinct Ys -> no row exceeds FAN_COLUMNS -> a single
 *  pass (the common path). */
function spreadPositions(graph: ElkNode): Map<string, { x: number; y: number }> {
  const positions = new Map<string, { x: number; y: number }>();
  (graph.children ?? []).forEach((child, i) => {
    positions.set(child.id, { x: 0, y: i * 200 });
  });
  return positions;
}

/** All children on one rounded Y -> one wide row of >FAN_COLUMNS -> forces pass 2. */
function wideRowPositions(graph: ElkNode): Map<string, { x: number; y: number }> {
  const positions = new Map<string, { x: number; y: number }>();
  (graph.children ?? []).forEach((child, i) => {
    positions.set(child.id, { x: i * PITCH_X, y: 0 });
  });
  return positions;
}

interface FakeElk extends ElkLike {
  layoutCalls: ElkNode[];
  terminateCount: number;
  deferreds: Deferred<ElkNode>[];
}

/** A fake ELK whose layout() returns a pending, externally-resolvable promise per
 *  call and whose terminateWorker() counts calls. */
function makeFakeElk(): FakeElk {
  const fake: FakeElk = {
    layoutCalls: [],
    terminateCount: 0,
    deferreds: [],
    layout(graph: ElkNode): Promise<ElkNode> {
      fake.layoutCalls.push(graph);
      const d = deferred<ElkNode>();
      fake.deferreds.push(d);
      return d.promise;
    },
    terminateWorker(): void {
      fake.terminateCount += 1;
    },
  };
  return fake;
}

/** A counting factory over a single fake instance (so reuse across runs is
 *  observable via callCount while the same instance is returned each time). */
function countingFactory(fake: ElkLike): ElkFactory & { callCount: number } {
  const factory = (() => {
    factory.callCount += 1;
    return fake;
  }) as ElkFactory & { callCount: number };
  factory.callCount = 0;
  return factory;
}

/** Flush microtasks so chained awaits inside getDirectedLayout advance. */
async function flush(): Promise<void> {
  await Promise.resolve();
  await Promise.resolve();
}

// --- Module-state reset via the public abort path ----------------------------

/** Reset the module-level elkInstance to null via the PUBLIC abort path (an
 *  aborted run runs resetElk() and nulls the cell) — no test-only export. Uses a
 *  throwaway fake whose layout() never resolves; aborting terminates whatever
 *  instance is live and nulls the cell. */
async function resetElkViaAbort(): Promise<void> {
  const fake = makeFakeElk();
  const controller = new AbortController();
  const run = getDirectedLayout(archNodes(1), NO_EDGES, {
    signal: controller.signal,
    elkFactory: () => fake,
  });
  await flush(); // let getElk + the first layout() call happen
  controller.abort();
  await expect(run).rejects.toBe(LAYOUT_ABORTED);
}

beforeEach(async () => {
  await resetElkViaAbort();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("getDirectedLayout abort seam", () => {
  it("terminates the worker and rejects LAYOUT_ABORTED when aborted mid-flight (TS-03-01)", async () => {
    const fake = makeFakeElk();
    const factory = countingFactory(fake);
    const controller = new AbortController();

    const run = getDirectedLayout(archNodes(3), NO_EDGES, {
      signal: controller.signal,
      elkFactory: factory,
    });
    await flush();
    // Pass 1 is in flight (its layout() promise never resolves).
    expect(fake.layoutCalls).toHaveLength(1);
    expect(fake.terminateCount).toBe(0);

    controller.abort();
    await expect(run).rejects.toBe(LAYOUT_ABORTED);
    // The worker was terminated (real cancellation), and the run did not hang on
    // the now-dead layout promise.
    expect(fake.terminateCount).toBe(1);
  });

  it("skips pass 2 when superseded between passes (TS-03-02)", async () => {
    const fake = makeFakeElk();
    const factory = countingFactory(fake);
    const controller = new AbortController();

    const run = getDirectedLayout(archNodes(WIDE_ROW_COUNT), NO_EDGES, {
      signal: controller.signal,
      elkFactory: factory,
    });
    await flush();
    expect(fake.layoutCalls).toHaveLength(1);

    // Resolve pass 1 with a single wide row (>FAN_COLUMNS) so pass 2 WOULD run...
    fake.deferreds[0].resolve(resultFor(fake.layoutCalls[0], wideRowPositions(fake.layoutCalls[0])));
    // ...but abort before the between-passes check lets pass 2 start.
    controller.abort();

    await expect(run).rejects.toBe(LAYOUT_ABORTED);
    // layout() was invoked exactly once: the between-passes abort check skipped
    // pass 2 entirely.
    expect(fake.layoutCalls).toHaveLength(1);
    expect(fake.terminateCount).toBe(1);
  });

  it("reuses one ELK instance and never terminates on the non-superseded path (TS-03-03)", async () => {
    const fake = makeFakeElk();
    const factory = countingFactory(fake);

    // Run A: spread positions => no wide row => single pass => completes.
    const runA = getDirectedLayout(archNodes(3), NO_EDGES, { elkFactory: factory });
    await flush();
    expect(fake.layoutCalls).toHaveLength(1);
    fake.deferreds[0].resolve(resultFor(fake.layoutCalls[0], spreadPositions(fake.layoutCalls[0])));
    const positionsA = await runA;
    expect(positionsA).toHaveLength(3);

    // Run B: same fake, sequential.
    const runB = getDirectedLayout(archNodes(2), NO_EDGES, { elkFactory: factory });
    await flush();
    expect(fake.layoutCalls).toHaveLength(2);
    fake.deferreds[1].resolve(resultFor(fake.layoutCalls[1], spreadPositions(fake.layoutCalls[1])));
    const positionsB = await runB;
    expect(positionsB).toHaveLength(2);

    // One instance reused across both runs (factory called once), and the worker
    // was never terminated on the common path — no churn.
    expect(factory.callCount).toBe(1);
    expect(fake.terminateCount).toBe(0);
  });

  it("lazily recreates the ELK instance after an abort (TS-03-04)", async () => {
    const fake = makeFakeElk();
    const factory = countingFactory(fake);

    // First run: aborted mid-flight -> instance torn down.
    const controller = new AbortController();
    const aborted = getDirectedLayout(archNodes(3), NO_EDGES, {
      signal: controller.signal,
      elkFactory: factory,
    });
    await flush();
    expect(factory.callCount).toBe(1);
    controller.abort();
    await expect(aborted).rejects.toBe(LAYOUT_ABORTED);
    expect(fake.terminateCount).toBe(1);

    // Second run after the abort: the instance was nulled, so the factory is
    // invoked again to lazily create a fresh one.
    const fresh = getDirectedLayout(archNodes(2), NO_EDGES, { elkFactory: factory });
    await flush();
    expect(factory.callCount).toBe(2);
    fake.deferreds[fake.deferreds.length - 1].resolve(
      resultFor(fake.layoutCalls[fake.layoutCalls.length - 1], spreadPositions(fake.layoutCalls[fake.layoutCalls.length - 1])),
    );
    await fresh;
  });
});

describe("getDirectedLayout stale-result guard", () => {
  it("a superseded run rejects and never produces positions, so it cannot overwrite a newer run (TS-04-01)", async () => {
    // Run A over its own fake, aborted mid-flight.
    const fakeA = makeFakeElk();
    const controllerA = new AbortController();
    const runA = getDirectedLayout(archNodes(3), NO_EDGES, {
      signal: controllerA.signal,
      elkFactory: () => fakeA,
    });
    await flush();
    expect(fakeA.layoutCalls).toHaveLength(1);

    let aResolvedPositions: unknown = null;
    runA.then((p) => {
      aResolvedPositions = p;
    }).catch(() => {
      /* expected LAYOUT_ABORTED */
    });

    controllerA.abort();
    await expect(runA).rejects.toBe(LAYOUT_ABORTED);
    expect(fakeA.terminateCount).toBe(1);

    // After A is torn down, run B (a fresh instance) completes successfully.
    const fakeB = makeFakeElk();
    const runB = getDirectedLayout(archNodes(2), NO_EDGES, { elkFactory: () => fakeB });
    await flush();
    expect(fakeB.layoutCalls).toHaveLength(1);
    fakeB.deferreds[0].resolve(resultFor(fakeB.layoutCalls[0], spreadPositions(fakeB.layoutCalls[0])));
    const positionsB = await runB;

    // B produced positions; A never yielded a position array (it rejected), so a
    // superseded run cannot overwrite the newer result.
    expect(positionsB).toHaveLength(2);
    expect(aResolvedPositions).toBeNull();
  });
});

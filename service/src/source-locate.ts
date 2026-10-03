import { isAlias, isMap, isScalar, isSeq, LineCounter, parseDocument, type Node } from "yaml";

/** Where a JSON Pointer's value sits in the submitted text. */
export interface SourceNode {
  /** 1-based line of the node — of its key, when the node is a mapping value. */
  line: number;
  /** Set when the node is a scalar: its text as written, and the mapping key it sits under. */
  scalar?: { source: string; key?: string };
}

export type Locator = (pointer: string) => SourceNode | undefined;

/**
 * Locate JSON Pointers in the submitted text with a second, position-keeping
 * parse. The validated value comes from the js-yaml / JSON.parse result; this
 * parse only maps pointers to nodes. The document is parsed on the first call,
 * so a valid artifact never pays for it.
 */
export function sourceLocator(text: string): Locator {
  let parsed: { doc: ReturnType<typeof parseDocument>; lines: LineCounter } | undefined;
  return (pointer) => {
    if (!parsed) {
      const lines = new LineCounter();
      parsed = { doc: parseDocument(text, { lineCounter: lines, merge: true }), lines };
    }
    const { doc, lines } = parsed;
    const segments = pointer === "" ? [] : pointer.slice(1).split("/").map(unescapeSegment);

    let node: unknown = doc.contents;
    let keyNode: Node | undefined;
    let key: string | undefined;
    for (const seg of segments) {
      node = isAlias(node) ? node.resolve(doc) : node;
      if (isMap(node)) {
        const pair = node.items.find((p) => isScalar(p.key) && String(p.key.value) === seg);
        if (!pair) return undefined;
        node = pair.value;
        keyNode = pair.key as Node;
        key = seg;
      } else if (isSeq(node)) {
        const idx = Number(seg);
        if (!Number.isInteger(idx)) return undefined;
        node = node.items[idx];
        keyNode = undefined;
        key = undefined;
      } else {
        return undefined;
      }
    }
    node = isAlias(node) ? node.resolve(doc) : node;
    const anchor = (keyNode ?? node) as Node | null | undefined;
    if (!anchor?.range) return undefined;

    const out: SourceNode = { line: lines.linePos(anchor.range[0]).line };
    if (isScalar(node) && node.range) {
      out.scalar = {
        source: shorten(text.slice(node.range[0], node.range[1])),
        ...(key !== undefined ? { key } : {}),
      };
    }
    return out;
  };
}

function unescapeSegment(s: string): string {
  return s.replace(/~1/g, "/").replace(/~0/g, "~");
}

function shorten(source: string): string {
  const first = source.split("\n", 1)[0]!;
  const cut = first.length <= 60 ? first : first.slice(0, 57);
  return cut === source ? source : `${cut}…`;
}

// postMessage groundwork for the iframe <-> parent (webathome.org) channel.
// v0 has no consumers; this exists so retrofitting later is cheap.
//
// Contract:
//   - Inbound:  { type: "set-view", view: string } from PARENT_ORIGIN only.
//   - Outbound: { type: "ready" } on mount.
//               { type: "view-change", view: string } when the viewer's filter
//               state changes (wired by ArchitectureMap once a view model exists).

const PARENT_ORIGIN = "https://webathome.org";

type InboundMessage = { type: "set-view"; view: string };
type OutboundMessage =
  | { type: "ready" }
  | { type: "view-change"; view: string };

type SetViewHandler = (view: string) => void;

let setViewHandler: SetViewHandler | null = null;

export function onSetView(handler: SetViewHandler): () => void {
  setViewHandler = handler;
  return () => {
    if (setViewHandler === handler) {
      setViewHandler = null;
    }
  };
}

export function emitToParent(message: OutboundMessage): void {
  if (window.parent === window) {
    return;
  }
  window.parent.postMessage(message, PARENT_ORIGIN);
}

export function initParentBridge(): void {
  window.addEventListener("message", (event: MessageEvent) => {
    if (event.origin !== PARENT_ORIGIN) {
      return;
    }
    const data = event.data as InboundMessage | undefined;
    if (!data || typeof data !== "object") {
      return;
    }
    if (data.type === "set-view" && typeof data.view === "string") {
      setViewHandler?.(data.view);
    }
  });

  emitToParent({ type: "ready" });
}

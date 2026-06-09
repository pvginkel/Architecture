import { Focus, Minus, Plus } from "lucide-react";
import { Panel } from "@xyflow/react";
import { KIND_LABELS } from "../generated/vocab";
import type { ArchElement } from "../data/model";

interface SelectionPanelProps {
  element: ArchElement;
  // The selected node's expansion level: the hop radius Expand has grown it to.
  // 0 means it is not an anchor, so there is nothing to collapse.
  level: number;
  onIsolate: () => void;
  onExpand: () => void;
  onCollapse: () => void;
}

// Floating control that appears beside the zoom controls when a node is
// selected. It drives the three graph-navigation actions; see
// computeExpandedVisibleGraph for how Isolate/Expand feed the visible set.
export function SelectionPanel({
  element,
  level,
  onIsolate,
  onExpand,
  onCollapse,
}: SelectionPanelProps) {
  return (
    <Panel position="bottom-left" className="selection-panel">
      <div className="selection-panel__head">
        <span className="selection-panel__label" title={element.label}>
          {element.label}
        </span>
        <span className="selection-panel__kind">{KIND_LABELS[element.kind]}</span>
      </div>
      <div className="selection-panel__actions">
        <button
          type="button"
          className="selection-panel__button"
          onClick={onIsolate}
          title="Clear the canvas and show only this node"
        >
          <Focus size={15} />
          Isolate
        </button>
        <button
          type="button"
          className="selection-panel__button"
          onClick={onExpand}
          title="Add this node's directly linked neighbours (following the selected relationship types)"
        >
          <Plus size={15} />
          Expand
        </button>
        <button
          type="button"
          className="selection-panel__button"
          onClick={onCollapse}
          disabled={level === 0}
          title="Remove the outermost ring this node expanded"
        >
          <Minus size={15} />
          Collapse
        </button>
      </div>
      <div className="selection-panel__level">
        Expansion level <strong>{level}</strong>
      </div>
    </Panel>
  );
}

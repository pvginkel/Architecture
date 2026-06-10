import { Waypoints } from "lucide-react";
import { Panel } from "@xyflow/react";

interface EdgeSelectionPanelProps {
  // Whether the selected edge is a render-time-derived bridge (only those have a
  // hidden path to expand). Asserted edges show the panel with the action
  // disabled, so the affordance is discoverable but inert.
  derived: boolean;
  // Number of hidden nodes the derived path spans, for the button hint.
  hopCount: number;
  onExpandDerivedPath: () => void;
}

// Floating control mirroring the node SelectionPanel, shown when a relationship
// is selected. Its one action reveals the hidden nodes a derived edge bridges
// (see deriveBridges' `via` and ArchitectureMap's revealedIds).
export function EdgeSelectionPanel({
  derived,
  hopCount,
  onExpandDerivedPath,
}: EdgeSelectionPanelProps) {
  return (
    <Panel position="bottom-left" className="selection-panel">
      <button
        type="button"
        className="selection-panel__button"
        onClick={onExpandDerivedPath}
        disabled={!derived || hopCount === 0}
        title={
          derived
            ? `Reveal the ${hopCount} hidden node(s) this derived relationship bridges`
            : "Only derived relationships have a hidden path to expand"
        }
      >
        <Waypoints size={16} />
        Expand derived path
      </button>
    </Panel>
  );
}

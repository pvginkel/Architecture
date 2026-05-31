import { Search, X, type LucideProps } from "lucide-react";
import type { ComponentType, ReactNode } from "react";
import { KIND_ICON, LAYER_ACCENT } from "../theme";
import type { ElementKind, LayerId } from "../generated/vocab";
import { FilterGroup } from "./FilterGroup";
import type { FilterGroupModel } from "./groups";
import { KIND_GROUP, LAYER_GROUP, type FilterState } from "./state";

interface FilterRailProps {
  groups: FilterGroupModel[];
  filterState: FilterState;
  collapsed: Record<string, boolean>;
  searchTerm: string;
  onSearch: (term: string) => void;
  onToggleCollapse: (groupId: string) => void;
  onToggleOption: (groupId: string, value: string) => void;
  onSelectAll: (groupId: string, values: string[]) => void;
  onClear: () => void;
}

// Element-type rows carry the kind glyph; Layer rows carry the layer colour
// swatch. Other groups are label + count only.
function optionIconFor(groupId: string): ((value: string) => ReactNode) | undefined {
  if (groupId === KIND_GROUP) {
    return (value) => {
      const Icon = KIND_ICON[value as ElementKind] as ComponentType<LucideProps> | undefined;
      return Icon ? <Icon size={14} /> : null;
    };
  }
  if (groupId === LAYER_GROUP) {
    return (value) => (
      <span className="filter-swatch" style={{ background: LAYER_ACCENT[value as LayerId] }} />
    );
  }
  return undefined;
}

const EMPTY_SELECTION = new Set<string>();

export function FilterRail({
  groups,
  filterState,
  collapsed,
  searchTerm,
  onSearch,
  onToggleCollapse,
  onToggleOption,
  onSelectAll,
  onClear,
}: FilterRailProps) {
  return (
    <aside className="filter-rail">
      <div className="filter-rail__search">
        <label className="search-box">
          <Search size={16} />
          <input
            value={searchTerm}
            onChange={(event) => onSearch(event.target.value)}
            placeholder="Search elements"
          />
        </label>
      </div>

      <div className="filter-rail__groups">
        {groups.map((group) => (
          <FilterGroup
            key={group.id}
            group={group}
            selected={filterState.get(group.id) ?? EMPTY_SELECTION}
            collapsed={collapsed[group.id] ?? false}
            onToggleCollapse={() => onToggleCollapse(group.id)}
            onToggleOption={(value) => onToggleOption(group.id, value)}
            onSelectAll={(values) => onSelectAll(group.id, values)}
            optionIcon={optionIconFor(group.id)}
          />
        ))}
      </div>

      <div className="filter-rail__footer">
        <button className="filter-rail__clear" onClick={onClear} type="button">
          <X size={16} />
          Clear filters
        </button>
      </div>
    </aside>
  );
}

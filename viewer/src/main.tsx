import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "@xyflow/react/dist/style.css";
import "./styles/architecture.css";
import { ArchitectureMap } from "./components/ArchitectureMap";
import { initParentBridge } from "./parent-bridge";

const container = document.getElementById("root");
if (!container) {
  throw new Error("missing #root element");
}

createRoot(container).render(
  <StrictMode>
    <ArchitectureMap />
  </StrictMode>,
);

initParentBridge();

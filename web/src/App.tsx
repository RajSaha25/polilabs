import { LeftRail } from "./components/LeftRail";
import { ViewerStub } from "./components/ViewerStub";

/** Three-pane research shell: left rail / Text panel / Decomp panel.
 *  The shell itself never scrolls — each pane scrolls independently.
 *  Phase 1 ships the left rail (the agent path); the Text and Decomp
 *  panes are placeholders until Phases 2-4. */
export default function App() {
  return (
    <div
      className="grid h-full overflow-hidden"
      style={{ gridTemplateColumns: "320px minmax(0, 1fr) 380px" }}
    >
      <LeftRail />
      <ViewerStub kind="text" />
      <ViewerStub kind="decomp" />
    </div>
  );
}

import { LeftRail } from "./components/LeftRail";
import { BillViewer } from "./components/BillViewer";

/** Research shell: the left rail (agent path) beside the bill viewer.
 *  The viewer is a carousel of bill panes — each pane is the verbatim
 *  Text panel next to the structured Decomp panel. The shell never
 *  scrolls; panes scroll independently. */
export default function App() {
  return (
    <div
      className="grid h-full overflow-hidden"
      style={{ gridTemplateColumns: "320px minmax(0, 1fr)" }}
    >
      <LeftRail />
      <BillViewer />
    </div>
  );
}

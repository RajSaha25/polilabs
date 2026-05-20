import { useEffect } from "react";
import useEmblaCarousel from "embla-carousel-react";
import { useAppStore } from "../store/useAppStore";
import { useEffectiveMode } from "../decomp/selectMode";
import { BillPane } from "./BillPane";

/** The bill viewer — an Embla carousel over the ranked bills. One
 *  slide per bill. `selectedBillIndex` in the store is the single
 *  source of truth: clicking the left-rail bill list scrolls the
 *  carousel; swiping the carousel writes the index back. */
export function BillViewer() {
  const bills = useAppStore((s) => s.rankedBills);
  const selectedIndex = useAppStore((s) => s.selectedBillIndex);
  const selectBill = useAppStore((s) => s.selectBill);
  const loadBill = useAppStore((s) => s.loadBill);
  const loadDefinedTerms = useAppStore((s) => s.loadDefinedTerms);
  const loadAmendments = useAppStore((s) => s.loadAmendments);

  const selectedBill = selectedIndex >= 0 ? bills[selectedIndex] : null;
  const selectedMode = useEffectiveMode(selectedBill?.bill_id ?? "");

  const [emblaRef, emblaApi] = useEmblaCarousel({ loop: false, align: "start" });

  // carousel settles on a slide -> store
  useEffect(() => {
    if (!emblaApi) return;
    const onSelect = () => selectBill(emblaApi.selectedScrollSnap());
    emblaApi.on("select", onSelect);
    return () => {
      emblaApi.off("select", onSelect);
    };
  }, [emblaApi, selectBill]);

  // the bill set changed (new query) -> rebuild the carousel
  useEffect(() => {
    emblaApi?.reInit();
  }, [emblaApi, bills]);

  // store -> carousel (a left-rail click). Guarded so it never fights
  // the user's own swipe.
  useEffect(() => {
    if (!emblaApi || selectedIndex < 0) return;
    if (emblaApi.selectedScrollSnap() !== selectedIndex) {
      emblaApi.scrollTo(selectedIndex);
    }
  }, [emblaApi, selectedIndex]);

  // fetch the active bill's section tree (idempotent + cached)
  useEffect(() => {
    if (selectedBill) void loadBill(selectedBill.bill_id);
  }, [selectedBill, loadBill]);

  // fetch the active bill's Decomp data for the current mode — only the
  // selected bill, only what the mode needs (idempotent + cached)
  useEffect(() => {
    if (!selectedBill) return;
    if (selectedMode === "definition") {
      void loadDefinedTerms(selectedBill.bill_id);
    } else if (selectedMode === "amendment") {
      void loadAmendments(selectedBill.bill_id);
    }
  }, [selectedBill, selectedMode, loadDefinedTerms, loadAmendments]);

  if (bills.length === 0) {
    return (
      <div className="flex h-full items-center justify-center bg-paper">
        <p className="max-w-sm text-center text-sm text-ink-faint">
          Ask a question in the left rail. The bills behind the answer
          appear here — each readable as verbatim text.
        </p>
      </div>
    );
  }

  return (
    <div className="h-full overflow-hidden bg-paper" ref={emblaRef}>
      <div className="flex h-full">
        {bills.map((bill) => (
          <div key={bill.bill_id} className="h-full min-w-0 flex-[0_0_100%]">
            <BillPane bill={bill} />
          </div>
        ))}
      </div>
    </div>
  );
}

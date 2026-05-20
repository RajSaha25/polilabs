/** Short locator from a canonical citation:
 *  "Sec. 3(b) of H.R. 1736, 119th Cong." -> "Sec. 3(b)". */
export function locator(citation: string): string {
  const head = citation.split(" of ")[0]?.trim();
  return head || "§";
}

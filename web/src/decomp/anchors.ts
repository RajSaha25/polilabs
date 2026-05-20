/** A Decomp item, reduced to what the synced highlight needs: a stable
 *  id, the section it anchors to, and the verbatim string to locate in
 *  the Text panel. Both Decomp cards and the Text panel's reverse-marks
 *  derive from the same anchor list, so the two directions stay in sync. */

import type { AmendmentsResult, DefinedTermsResult } from "../api/types";

export interface DecompAnchor {
  itemId: string;
  sectionId: string;
  text: string;
}

export function definitionAnchors(
  result: DefinedTermsResult,
): DecompAnchor[] {
  return result.terms.map((term) => ({
    itemId: term.defined_term_id,
    sectionId: term.defining_section_id,
    text: term.definition_text,
  }));
}

/** The verbatim span an amendment anchors to in the bill's *own* text:
 *  the quoted new-law block (`after_text`). A pure strike or repeal has
 *  no new text, so fall back to the struck text (`before_text`). */
export function amendmentHighlightText(amendment: {
  after_text: string;
  before_text: string | null;
}): string {
  if (amendment.after_text && amendment.after_text.trim()) {
    return amendment.after_text;
  }
  return amendment.before_text ?? "";
}

export function amendmentAnchors(
  result: AmendmentsResult,
): DecompAnchor[] {
  return result.amendments
    .map((amendment) => ({
      itemId: amendment.amendment_id,
      sectionId: amendment.source_section_id,
      text: amendmentHighlightText(amendment),
    }))
    .filter((anchor) => anchor.text.length > 0);
}

import type { BookLookup, GoogleBooksMatch } from "../../api/generated/model";

/**
 * What the confirm step is editing.
 *
 * Either the metadata a source returned, or (when neither knew the ISBN) a
 * blank draft the member fills in themselves. `notFound` is what tells the UI
 * to show editable fields instead of a read-only summary; it is client state
 * and is never sent to the API.
 */
export interface BookDraft extends BookLookup {
  notFound?: boolean;
}

export function draftFromLookup(lookup: BookLookup): BookDraft {
  return { ...lookup };
}

export function blankDraft(isbn: string): BookDraft {
  return { isbn, title: "", suggested_tag_ids: [], notFound: true };
}

/**
 * Prefill the confirm step from a chosen search result.
 *
 * `notFound` is deliberately left off: the fields came from a real record, so
 * the summary view is right, and someone who wants to change one can still
 * edit it. The ISBN falls back to empty rather than being dropped, because a
 * book found by title genuinely may not have one, and the server treats a
 * blank ISBN as absent rather than invalid.
 */
export function draftFromGoogleMatch(match: GoogleBooksMatch): BookDraft {
  return {
    isbn: match.isbn13 ?? "",
    title: match.title ?? "",
    subtitle: match.subtitle,
    author: match.author,
    publisher: match.publisher,
    year: match.year,
    description: match.description,
    cover_url: match.cover_url,
    suggested_tag_ids: match.suggested_tag_ids ?? [],
  };
}

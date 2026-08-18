/**
 * Linking out to Goodreads.
 *
 * A link, not an integration, and that is not a shortcut. Goodreads shut its
 * public API to new developers in December 2020 and has issued no keys since,
 * so there is no supported way to authenticate an account or read a shelf
 * live. Importing a CSV export and linking out to search are the two things
 * that actually work.
 *
 * Mirrors `backend/goodreads.py:search_url`. It is duplicated rather than
 * fetched because building a search URL is pure string work and a round trip
 * per rendered title would be absurd.
 */

const SEARCH_BASE = "https://www.goodreads.com/search";

/**
 * Where to send someone looking for this book.
 *
 * The ISBN wins when there is one: a title search for "Dune" returns dozens
 * of editions, an ISBN search returns the edition on the shelf.
 */
export function searchUrl(title: string, isbn?: string | null): string {
  const query = isbn?.trim() ? isbn.trim() : title;
  return `${SEARCH_BASE}?q=${encodeURIComponent(query)}`;
}

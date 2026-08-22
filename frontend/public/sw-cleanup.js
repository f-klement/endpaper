/**
 * Imported into the generated service worker (see `workbox.importScripts` in
 * `vite.config.ts`).
 *
 * The `book-covers` runtime cache held remote cover images under `CacheFirst`
 * with no response check, so an opaque 404 was served as a book's cover for
 * thirty days without the network ever being consulted. The rule that replaced
 * it writes to `book-covers-v2` instead, and renaming is what orphans the bad
 * entries rather than inheriting them.
 *
 * Orphaned is not deleted. `cleanupOutdatedCaches` only touches precaches from
 * earlier builds, so without this the old cache sits in the reader's storage
 * quota for ever, holding answers nothing will ever read again.
 *
 * Safe to keep after everyone has updated: deleting a cache that is not there
 * resolves false and costs nothing.
 */
self.addEventListener("activate", (event) => {
  event.waitUntil(caches.delete("book-covers"));
});

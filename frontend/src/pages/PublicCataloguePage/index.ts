/**
 * The published catalogue's public surface.
 *
 * Two screens, and they are the **only** two routes in this application that
 * render without a session. `app/App.tsx` mounts them above the session gate
 * and `app/routes.tsx` mounts them again inside it, so a member following a
 * link to a public record gets the record rather than a 404. Both tables read
 * this barrel.
 */

export { default } from "./PublicCataloguePage";
export { default as PublicBookPage } from "./PublicBookPage";

/**
 * Height of a page's body: the viewport minus the fixed chrome above and below
 * it (topbar + the page's own top and bottom padding).
 *
 * A table page sets this on its root and then lets the table card flex to fill
 * what's left, so the TABLE scrolls and the window doesn't. Without it the page
 * grows past the viewport and the pager scrolls off the bottom — you lose the
 * column headers and the page controls the moment you look at row 30.
 *
 * It's a bare `var()` rather than the calc itself so index.css owns the value:
 * --page-pad shrinks on short viewports, dvh replaces vh where supported, and
 * the mobile breakpoint switches the whole thing to `auto` so a phone scrolls
 * the page normally. None of that is expressible from here.
 */
export const PAGE_BODY_HEIGHT = "var(--page-body-h)";

# Theming

Seven palettes, two modes each, and the rule that generated every rung of them.

| Where | What |
|---|---|
| `frontend/src/index.css` | The tokens themselves, which are Endpaper's light values, plus Endpaper's dark corrections |
| `frontend/src/theme/palettes.css` | The other six palettes, as `data-theme` blocks |
| `frontend/src/theme/palettes.ts` | The catalogue: the list, the attributions, and which member was constructed |
| `frontend/src/theme/appearance.ts` | The per account preference and its write-through cache |
| `frontend/tests/theme/palettes.test.ts` | The contract below, measured against the shipped stylesheets |

## The seven

| Palette | Modes | Attribution |
|---|---|---|
| Endpaper | light, dark | This project |
| Catppuccin | Latte, Mocha | Catppuccin, MIT |
| Rose Pine | Dawn, Moon | Rose Pine, MIT |
| Gruvbox | light, dark | Pavel Pertsev, MIT |
| Solarized | light, dark | Ethan Schoonover, MIT |
| Everforest | Medium light, Medium dark | sainnhe, MIT |
| Nord | dark published, light constructed | Arctic Ice Studio and Sven Greb, MIT |

All six upstream palettes are MIT licensed and the values are taken from each project's own
repository rather than from a documentation site, which in at least one case carries a
different licence. None of these projects endorses this one.

**Mode is an independent axis and no palette may disable it.** Nord publishes no light
theme, so its light member is built from Snow Storm (the surfaces) and Polar Night (the
ink), both published sets, with the roles assigned here. The catalogue records that as
`constructed: ["light"]` and the picker says so. The alternative, a palette that greys out
the light and dark control every other palette leaves alone, makes one theme a special case
of a control and silently ignores a choice somebody made.

### The wallpaper names

The five wallpapers are named for the historical Morris designs the drawings are after.
Those names, "Willow Bough", "Strawberry Thief", "Golden Lily", "Pimpernel" and "Acanthus",
are also current product names of Morris & Co, a live trading brand. The designs are public
domain; the names are in commercial use, which is a trademark question rather than a
copyright one, and the two do not expire together.

Naming a design by the name its author gave it is nominative use in its strongest form:
these are the historical titles, used as such by the V&A and in every scholarly catalogue,
and there is no alternative name for Strawberry Thief. The rule this is an instance of:
**name the tradition, not a product; use the historical title where one exists; never a mark
that only a company uses.**

> The Morris pattern names identify the historical designs the drawings are after. This
> project is not affiliated with, or endorsed by, Morris & Co.

## The rule that generates a ramp

**Lightness belongs to this app, hue and chroma belong to the palette.**

No upstream publishes eleven rungs of an accent or twelve of a neutral, so generating the
missing ones is the method rather than a deviation. A published value is kept verbatim
wherever it clears the rung it lands on, and corrected in OKLab lightness with its hue and
chroma held (and clipped back into sRGB) wherever it does not. Every correction is tabulated
below with the number that forced it.

The correction is a bisection on OKLab lightness with the hue and the chroma
held, and three details decide whether two people doing it get the same hex:

- **The target is the floor itself**, not a margin above it. A corrected rung
  lands on 3.00, 4.51, 6.00 or 7.00 rather than somewhere comfortable past them,
  so the deviation tables below say exactly how much the palette had to give up
  and nothing more.
- **Chroma is clipped, never traded.** Moving lightness can take a saturated
  colour out of sRGB. The chroma is bisected down to the largest value that
  still lands inside it at that lightness and hue, so what gives way is the
  saturation the display cannot show anyway, and the hue never moves.
- **Missing rungs are interpolated in OKLab between the two published
  neighbours**, at the position the rung sits at in the list, and extrapolated
  past the last anchor along the slope of the last two. Above a dark palette's
  brightest published ink the extrapolation saturates (three rungs land on the
  same near white), so those are mixed from the body ink toward white at 0.35,
  0.60 and 0.85 instead, which keeps the palette's own tint in them.

One rung is corrected against **every background it is painted on, in
sequence**, not against one. That is what the pair tables below are: `bloom-600`
is darkened until it clears the card, then the page, then its own tint, each
correction starting from the result of the last. It matters most on the
semantic ramps, where a rung sits on a tint made of the same hue, and it is the
step an implementation reading only the bisection rule will miss.

A ramp is then straightened: each rung must be at least 0.005 in OKLab lightness
from its neighbour, and a rung that overtook one is pushed back to 0.007. The
threshold is small deliberately, because two published surfaces legitimately sit
that close (the default palette's card and page are 1.04:1 apart). Straightening
moves a tint as well, so the rungs measured against their own tint are checked
again afterwards.

Three placement rules decide which rung a published colour lands on:

- **Surfaces by role.** The lightest published surface is the card, the next the page, the
  next the sunken tier, then the borders. In the dark the same list runs the other way from
  `950`.
- **The accent by the rung it can hold.** `600` if it can carry text on the card at 4.5,
  else `500`, which carries the focus ring at 3.0, else `400`, which carries no text and so
  has no floor. That is what keeps Catppuccin's teal (3.31 on Latte's base) and Everforest's
  olive (2.69 on its own background) verbatim instead of darkening them into colours those
  palettes do not contain.
- **Bloom and danger by lightness.** Neither has a single role the way the accent does, so
  the published colour goes to the rung whose lightness it already has and the ink steps are
  generated from there. Catppuccin's pink survives at `bloom-300` for that reason.

### The rung contract

Measured against the card, which is the harder of the two surfaces in both modes: in light
the card is brighter than the page, and in the dark it is dimmer.

```
light   400 >= 3.0   500 >= 4.5   700 >= 6.0   900 >= 7.0
dark    600 >= 3.0   500 >= 4.5   400 >= 6.0   300 >= 7.0
```

Body ink at `200` sits in an 8.5 to 16 band on the page. The ceiling is not decoration:
near white on near black is around 18:1, which is past legible and into glare, and a grid of
book titles reads as a row of lightbulbs.

Two rules live in the stylesheet rather than at any call site:

- **The dark primary button is a light fill with dark text.** White on `accent-600` fails in
  three of these palettes, so the fill, its hover and the foreground on it are three tokens
  that are overridden together.
- **`paper-400` and `paper-500` never carry text in light mode.** A house rule test asserts
  it. Retiring them as text is what lets several upstream mid greys stand as decoration.

### Two ramps per palette, not one

A single neutral ramp cannot serve both modes. Light `500` has to be dark enough to read on
white, which needs a relative luminance at or below 0.183; dark `500` has to be light enough
to read on near black, which needs 0.194 or above. No hex satisfies both, so every palette
here states a light ramp and a dark one, Endpaper included.

## What each palette cost

Published values kept verbatim, out of those the palette publishes at all:

| Palette | light paper | dark paper | corrections |
|---|---|---|---|
| Endpaper | 10/12 | 11/12 | 4 |
| Catppuccin | 5/10 | 7/9 | 8 |
| Rose Pine | 5/9 | 5/8 | 9 |
| Gruvbox | 8/11 | 7/10 | 8 |
| Solarized | 4/7 | 4/8 | 11 |
| Everforest | 5/8 | 6/8 | 7 |
| Nord | 7/7 | 7/7 | 4 |

Nord is the only palette that needs no neutral correction in either mode, which is not luck:
its neutrals are further apart than anybody else's. Solarized needs the most, because its
ink tiers are compressed against this app's (base01 through base1 span 2.4 to 4.9 on its own
dark card, where the contract wants 3.0 to 7.0).

## Every correction

### Endpaper, light

2 corrections.

| Rung | Upstream | Shipped | Was | Needed | Where it is read |
|---|---|---|---|---|---|
| `paper-400` | `#b0a89b` | `#9c9487` | 2.35 | 3.0 | on the card |
| `paper-500` | `#8a8175` | `#7e756a` | 3.83 | 4.5 | on the card |

### Endpaper, dark

2 corrections.

| Rung | Upstream | Shipped | Was | Needed | Where it is read |
|---|---|---|---|---|---|
| `paper-600` | `#6b6358` | `#6c6458` | 2.96 | 3.0 | on the card |
| `bloom-500` | `#e11d48` | `#f23555` | 3.73 | 4.5 | text on the card |

### Catppuccin, light

6 corrections.

| Rung | Upstream | Shipped | Was | Needed | Where it is read |
|---|---|---|---|---|---|
| `paper-400` | `#acb0be` | `#878b99` | 1.91 | 3.0 | on the card |
| `paper-500` | `#9ca0b0` | `#6a6d7c` | 2.3 | 4.5 | on the card |
| `paper-600` | `#6c6f85` | `#606277` | 4.37 | 4.5 | on the card |
| `paper-700` | `#5c5f77` | `#575971` | 5.53 | 6.0 | on the card |
| `paper-900` | `#4c4f69` | `#484b64` | 6.57 | 7.0 | on the page |
| `danger-500` | `#d20f39` | `#d10e39` | 4.46 | 4.5 | text on the page |

### Catppuccin, dark

2 corrections.

| Rung | Upstream | Shipped | Was | Needed | Where it is read |
|---|---|---|---|---|---|
| `paper-400` | `#a6adc8` | `#abb3ce` | 5.65 | 6.0 | on the card |
| `paper-500` | `#9399b2` | `#949ab3` | 4.45 | 4.5 | on the card |

### Rose Pine, light

6 corrections.

| Rung | Upstream | Shipped | Was | Needed | Where it is read |
|---|---|---|---|---|---|
| `paper-400` | `#cecacd` | `#949194` | 1.56 | 3.0 | on the card |
| `paper-500` | `#9893a5` | `#767183` | 2.87 | 4.5 | on the card |
| `paper-700` | `#797593` | `#625d7a` | 4.23 | 6.0 | on the card |
| `paper-900` | `#575279` | `#544e75` | 6.66 | 7.0 | on the page |
| `bloom-500` | `#d7827e` | `#a95957` | 2.74 | 4.5 | text on the card |
| `danger-500` | `#b4637a` | `#a7586f` | 4.04 | 4.5 | text on the card |

### Rose Pine, dark

3 corrections.

| Rung | Upstream | Shipped | Was | Needed | Where it is read |
|---|---|---|---|---|---|
| `paper-400` | `#908caa` | `#a8a4c3` | 4.46 | 6.0 | on the card |
| `paper-500` | `#6e6a86` | `#918daa` | 2.79 | 4.5 | on the card |
| `paper-600` | `#56526e` | `#736f8c` | 1.94 | 3.0 | on the card |

### Gruvbox, light

3 corrections.

| Rung | Upstream | Shipped | Was | Needed | Where it is read |
|---|---|---|---|---|---|
| `paper-400` | `#bdae93` | `#9a8b71` | 1.98 | 3.0 | on the card |
| `paper-500` | `#928374` | `#7c6d5f` | 3.33 | 4.5 | on the card |
| `paper-700` | `#665c54` | `#655b54` | 5.92 | 6.0 | on the card |

### Gruvbox, dark

5 corrections.

| Rung | Upstream | Shipped | Was | Needed | Where it is read |
|---|---|---|---|---|---|
| `paper-300` | `#d5c4a1` | `#d9c8a4` | 6.76 | 7.0 | on the card |
| `paper-400` | `#bdae93` | `#c8b99d` | 5.32 | 6.0 | on the card |
| `paper-500` | `#a89984` | `#afa08a` | 4.17 | 4.5 | on the card |
| `bloom-300` | `#d3869b` | `#dd8fa4` | 4.23 | 4.5 | text on the card |
| `danger-500` | `#fb4934` | `#ff7964` | 3.37 | 4.5 | text on the card |

### Solarized, light

5 corrections.

| Rung | Upstream | Shipped | Was | Needed | Where it is read |
|---|---|---|---|---|---|
| `paper-400` | `#93a1a1` | `#849192` | 2.48 | 3.0 | on the card |
| `paper-500` | `#839496` | `#647476` | 2.93 | 4.5 | on the card |
| `paper-700` | `#586e75` | `#4c6168` | 4.99 | 6.0 | on the card |
| `bloom-500` | `#d33682` | `#c82a78` | 4.21 | 4.5 | text on the card |
| `danger-500` | `#dc322f` | `#d22626` | 4.29 | 4.5 | text on the card |

### Solarized, dark

6 corrections.

| Rung | Upstream | Shipped | Was | Needed | Where it is read |
|---|---|---|---|---|---|
| `paper-300` | `#93a1a1` | `#b3c1c1` | 4.86 | 7.0 | on the card |
| `paper-400` | `#839496` | `#a2b4b6` | 4.11 | 6.0 | on the card |
| `paper-500` | `#657b83` | `#859ca4` | 2.92 | 4.5 | on the card |
| `paper-600` | `#586e75` | `#677d85` | 2.42 | 3.0 | on the card |
| `bloom-500` | `#d33682` | `#fc5ea4` | 2.86 | 4.5 | text on the card |
| `danger-500` | `#dc322f` | `#ff665a` | 2.81 | 4.5 | text on the card |

### Everforest, light

5 corrections.

| Rung | Upstream | Shipped | Was | Needed | Where it is read |
|---|---|---|---|---|---|
| `paper-400` | `#a6b0a0` | `#889283` | 2.08 | 3.0 | on the card |
| `paper-500` | `#939f91` | `#697467` | 2.56 | 4.5 | on the card |
| `paper-700` | `#5c6a72` | `#536068` | 5.18 | 6.0 | on the card |
| `bloom-500` | `#df69ba` | `#b24192` | 2.83 | 4.5 | text on the card |
| `danger-500` | `#f85552` | `#cf2b30` | 3.04 | 4.5 | text on the card |

### Everforest, dark

2 corrections.

| Rung | Upstream | Shipped | Was | Needed | Where it is read |
|---|---|---|---|---|---|
| `paper-400` | `#9da9a0` | `#abb7ae` | 5.12 | 6.0 | on the card |
| `paper-500` | `#859289` | `#919f95` | 3.84 | 4.5 | on the card |

### Nord, light

2 corrections.

| Rung | Upstream | Shipped | Was | Needed | Where it is read |
|---|---|---|---|---|---|
| `bloom-500` | `#b48ead` | `#815e7c` | 2.46 | 4.5 | text on the card |
| `danger-500` | `#bf616a` | `#a84c55` | 3.55 | 4.5 | text on the card |

### Nord, dark

2 corrections.

| Rung | Upstream | Shipped | Was | Needed | Where it is read |
|---|---|---|---|---|---|
| `bloom-500` | `#b48ead` | `#c8a2c1` | 3.55 | 4.5 | text on the card |
| `danger-500` | `#bf616a` | `#f59199` | 2.46 | 4.5 | text on the card |

## The measured result

Every theme and mode clears every pair. `frontend/tests/theme/palettes.test.ts` reads the
shipped stylesheets, resolves the cascade the way a browser does, and asserts the full list;
these are the headline rows from that run.

### Light

| pair | floor | endpaper | catppuccin | rosepine | gruvbox | solarized | everforest | nord |
|---|---|---|---|---|---|---|---|---|
| body on the page | 7.0 | 16.78 | 7.00 | 7.06 | 10.22 | 11.31 | 10.06 | 8.26 |
| secondary on the card | 6.0 | 9.18 | 6.04 | 6.01 | 6.00 | 6.05 | 6.01 | 6.40 |
| muted on the page | 4.5 | 5.67 | 4.92 | 4.78 | 5.03 | 4.81 | 4.73 | 5.02 |
| paper-500 on the card | 4.5 | 4.53 | 4.54 | 4.53 | 4.53 | 4.53 | 4.53 | 4.51 |
| paper-400 on the card | 3.0 | 3.00 | 3.00 | 3.00 | 3.02 | 3.02 | 3.00 | 3.00 |
| link on the card | 4.5 | 5.47 | 6.11 | 7.76 | 6.25 | 6.88 | 6.58 | 6.34 |
| fill pairing | 4.5 | 4.78 | 5.14 | 6.11 | 4.99 | 5.53 | 5.18 | 5.41 |
| hover pairing | 4.5 | 5.47 | 6.91 | 8.06 | 6.88 | 7.42 | 7.09 | 7.31 |
| focus ring on the page | 3.0 | 3.09 | 3.08 | 3.96 | 3.25 | 3.62 | 3.36 | 3.31 |
| bloom ink on its tint | 4.5 | 6.69 | 7.79 | 7.41 | 7.54 | 7.73 | 7.66 | 7.33 |
| danger text on the card | 4.5 | 6.29 | 6.28 | 5.85 | 4.90 | 6.03 | 5.05 | 5.21 |

### Dark

| pair | floor | endpaper | catppuccin | rosepine | gruvbox | solarized | everforest | nord |
|---|---|---|---|---|---|---|---|---|
| body on the page | 8.5 | 15.34 | 11.34 | 11.86 | 10.75 | 12.25 | 8.62 | 10.26 |
| body on the card | 7.0 | 13.94 | 8.69 | 10.90 | 8.45 | 10.61 | 7.38 | 8.26 |
| muted on the card | 6.0 | 7.43 | 6.03 | 6.00 | 6.01 | 6.03 | 6.01 | 6.04 |
| paper-500 on the card | 4.5 | 4.56 | 4.51 | 4.52 | 4.54 | 4.51 | 4.51 | 4.50 |
| paper-600 on the card | 3.0 | 3.00 | 3.40 | 3.00 | 3.16 | 3.00 | 3.21 | 3.01 |
| accent text on the card | 4.5 | 7.51 | 9.07 | 5.24 | 6.43 | 5.31 | 7.14 | 5.59 |
| fill pairing | 4.5 | 5.98 | 11.01 | 5.70 | 7.01 | 4.75 | 7.28 | 5.99 |
| hover pairing | 4.5 | 8.26 | 11.83 | 7.42 | 8.18 | 6.13 | 8.33 | 6.94 |
| focus ring on the page | 3.0 | 5.98 | 11.01 | 4.29 | 7.01 | 4.75 | 7.28 | 5.99 |
| bloom text on the card | 4.5 | 9.25 | 8.23 | 6.55 | 4.72 | 5.92 | 5.40 | 5.63 |
| danger text on the card | 4.5 | 9.25 | 5.43 | 7.96 | 6.01 | 5.92 | 4.76 | 4.80 |

## What the contract does not cover

Three things are outside it, and all three are real. They are recorded here
rather than left to be discovered, because a contract that is silent about its
own edges reads as a contract that has none.

**`warn`, `ok` and `loan` are not tokens.** Amber, green and orange are still
raw Tailwind at 29 lines across 16 files, so six of the seven palettes ship a
success message and an overdue badge in colours that belong to none of them.
It is not only coherence: `text-green-600` on the card measures **2.86 (Nord)
to 3.30 (Endpaper)** for text that needs 4.5, and it is the success message on
four screens. Each of those pairings is self-contained (`bg-amber-50` with
`text-amber-800`), which is why nothing here fails, and is also why nothing
here catches it.

**Dark hover is not covered.** Every ramp runs the other way in the dark, and
about twenty sites write `hover:text-accent-800` or `hover:text-danger-600`
with no `dark:` variant. Measured across the seven palettes they land between
**1.36 and 2.85** on the dark card: legible at rest, illegible while pointed
at. The two touched by this phase are repaired; the rest are a call site job
rather than a token one.

**The effort is currently inverted.** `paper-500` is held to 4.5 in all
fourteen theme-modes and painted at **zero** call sites, while the two lists
above are painted constantly and measured nowhere.

## What this does to the wallpaper

The wallpaper's ink is read off `accent-700` and `bloom-700` in light, and
`accent-300` and `bloom-300` in dark, so it now follows the palette without any
file that draws a tile knowing a hex. Two consequences, both measured, and the
second is for whoever does the retune.

The weight the ground layer carries at the shipped opacities, as an OKLab
lightness delta over each palette's own page:

| | light ground (target 0.026) | dark ground (target 0.061) |
|---|---|---|
| Endpaper | 0.0258 | 0.0580 |
| Catppuccin | 0.0250 | 0.0587 |
| Rose Pine | 0.0289 | 0.0427 |
| Gruvbox | 0.0263 | 0.0477 |
| Solarized | 0.0278 | 0.0441 |
| Everforest | 0.0259 | 0.0491 |
| Nord | 0.0247 | 0.0442 |

Light is within 11% of target everywhere. **Dark is not**: the palettes with a
dimmer ink land up to 30% under, so a single opacity cannot serve all seven
there.

The sharper version of the same fact: **the perceptual weight is now a function
of the palette, and the spread is as wide as the retune's own target band.** At
the heaviest tile's budget alpha the mean tile dL runs 0.00984 to 0.01252 in
light (1.27x) and 0.01435 to 0.01899 in dark (1.32x), while the agreed band,
0.0070 to 0.0092, is 1.31x wide. So the retune has to choose: an alpha solved
per palette, or one alpha with a stated tolerance. It cannot have a single
number and a tight band at the same time.

## Where an appearance is kept

Three nullable columns on `users`: `appearance_palette`, `appearance_mode`,
`appearance_wallpaper`. NULL means "has not chosen", which every account and every directory
shadow account starts as, and which the client renders as the system's mode, the house
palette, and a different wallpaper every visit.

They are columns rather than a `user_preferences` table because it is a one-to-one with no
history and no lifecycle of its own: a side table would add a join to every read and a row
that both shadow-account paths in `auth_backends.py` would have to remember to create.

**Appearance is not on `UserOut`.** That schema is served inside every book payload and the
member list, so a field there would show every member what every other member's library
looks like. It has its own pair of endpoints under `/api/users/me/appearance`, where there
is no path parameter and therefore no object to authorize: the only appearance reachable is
the caller's.

### The first paint

The server is the authority and `localStorage` is a write-through cache keyed by account.
The page is painted from the cache before React mounts, and reconciled when
`/api/users/me/appearance` answers. The only case that can still flash is a new account on a
new device, which is already waiting on the network.

The usual fix for that, an inline blocking `<script>`, is unavailable: `backend/middleware.py`
sets `script-src 'self'` with no nonce, so an inline script would need a per-build hash in
the CSP and the security middleware would have to be generated from the frontend bundle.
That was considered and rejected for that reason.

## More contrast

`@media (prefers-contrast: more)` moves the muted ink up one rung and turns the wallpaper
off. The ink half is in `index.css`; the wallpaper half is in `applyWallpaper`, so the
picker can say the system turned it off rather than showing an off state nobody chose.

The selector is `:root:root`, doubled. A palette block is `:root[data-theme="x"]` at
specificity (0,2,0) and a plain `:root` is (0,1,0), so written once the rule would apply on
Endpaper and be silently ignored on the other six.

## Adding a palette

1. Add its upstream anchors and its three seeds, and generate the two blocks under the rule
   above, which is written out in full so it can be re-implemented in whatever is to hand.
   Keep every published value that clears its rung.
2. Paste the blocks into `palettes.css` with a note saying what moved and why.
3. Add the entry to `PALETTES` in `palettes.ts`, with the attribution and any constructed
   mode.
4. Run `bun run test tests/theme/palettes.test.ts`. It measures the contract, the ramp
   order, the glare band and the completeness of both blocks. A palette that passes is
   finished; one that does not tells you which pair failed and by how much.

Two palettes were measured and not shipped, so adding either later is a data change rather
than a research project: **Dracula**, whose ramp needs eight of twelve neutrals generated
and whose light member exists only inside a commercial product, and **Kanagawa**, whose
light values could not be verified against upstream at the time.

# Theming

Ten palettes, two modes each, and the rule that generated every rung of them.

| Where | What |
|---|---|
| `frontend/src/index.css` | The tokens themselves, which are Endpaper's light values, plus Endpaper's dark corrections |
| `frontend/src/theme/palettes.css` | The other nine palettes, as `data-theme` blocks |
| `frontend/src/theme/palettes.ts` | The catalogue: the list, the attributions, and which member was constructed |
| `frontend/src/theme/appearance.ts` | The per account preference and its write-through cache |
| `frontend/src/pages/AppearancePage/` | The picker at `/settings/appearance/theme` |
| `frontend/tests/theme/palettes.test.ts` | The contract below, measured against the shipped stylesheets |

## The ten

| Palette | Modes | Attribution |
|---|---|---|
| Endpaper | light, dark | This project |
| Catppuccin | Latte, Mocha | Catppuccin, MIT |
| Rose Pine | Dawn, Moon | Rose Pine, MIT |
| Gruvbox | light, dark | Pavel Pertsev, MIT |
| Solarized | light, dark | Ethan Schoonover, MIT |
| Everforest | Medium light, Medium dark | sainnhe, MIT |
| Nord | dark published, light constructed | Arctic Ice Studio and Sven Greb, MIT |
| Kanagawa | Lotus, Wave | Tommaso Laurenzi, MIT |
| Tokyo Night | light, dark | Enkia, MIT |
| Ayu | light, dark | Konstantin Pschera, MIT |

All nine upstream palettes are MIT licensed and the values are taken from each project's own
repository rather than from a documentation site, which in at least one case carries a
different licence. None of these projects endorses this one.

**Which repository, for the three added last**, because for two of them the obvious one is
the wrong one: `rebelot/kanagawa.nvim`, `tokyo-night/tokyo-night-vscode-theme`, and
`ayu-theme/ayu-colors`. Ayu's editor plugins, `ayu-theme/ayu-vim` among them, are Apache 2.0
and only the colours repository is MIT; and the Tokyo Night everybody links to,
`folke/tokyonight.nvim`, is Apache 2.0 as well, where Enkia's original is MIT. A palette
whose licence is read off the theme's website rather than the file the values came from is a
licence read off the wrong thing.

**Mode is an independent axis and no palette may disable it.** Nord publishes no light
theme, so its light member is built from Snow Storm (the surfaces) and Polar Night (the
ink), both published sets, with the roles assigned here. The catalogue records that as
`constructed: ["light"]`, and the picker prints it on Nord's tile whenever light is the
mode in force. The alternative, a palette that greys out
the light and dark control every other palette leaves alone, makes one theme a special case
of a control and silently ignores a choice somebody made.

### What each member is called

The picker shows the palette's name and, under it, what upstream calls the member in force.
Only three publish one:

| Palette | Light | Dark |
|---|---|---|
| Catppuccin | Latte | Mocha |
| Rose Pine | Dawn | Moon |
| Everforest | Medium light | Medium dark |
| Kanagawa | Lotus | Wave |

The other six get no second line. "Gruvbox light" is not a title anybody uses, and Nord
names its colour groups rather than its themes: Polar Night and Snow Storm are the two
neutral sets its members are built out of, not the names of a light and a dark theme.

Tokyo Night and Ayu are the same rule seen from the other side, and both are worth stating
because each looks at first like a palette that does name its members. Tokyo Night publishes
three themes and Ayu three; in each case the third carries a name of its own, Storm and
Mirage, and in each case the third is not what is ported here. The two that are ported are
called by the palette's name plus the word for the mode, so there is nothing to print, and
printing "Storm" or "Mirage" would name a member this app does not ship.

### The wallpaper names

The rule, and both halves of the set are an instance of it: **name the tradition, not a
product; use the historical title where one exists; never a mark that only a company uses.**

Eight are named for the historical designs the drawings are after, seven of them Morris's
own and one his firm's. Those names are also current product names of Morris & Co, a live
trading brand. The designs are public domain; the names are in commercial use, which is a
trademark question rather than a copyright one, and the two do not expire together.

| Name | Designed | What is reproduced |
|---|---|---|
| Trellis | 1862, issued as wallpaper 1864 | The battened trellis and the wild rose climbing it. Morris's first wallpaper design. The birds on it are Philip Webb's and are not drawn, for the reason below the table |
| Jasmine | 1872 | Trails of jasmine over a ground of hawthorn foliage. The one design here whose subject is two plants, which is what the underfoliage plane is for |
| Acanthus | 1875 | The counter scrolling ogee of acanthus leaves |
| Marigold | 1875 | The turnover: radiating marigold heads on scrolling stems, registered as both a wallpaper and a printed textile |
| Pimpernel | 1876 | The ogee, with a bloom at the centre of each |
| Strawberry Thief | 1883 | The climbing stems and the fruit. The thieving birds are not drawn |
| Willow Bough | 1887 | The mass of willow leaves on serpentine stems |
| Golden Lily | 1899, and it is **John Henry Dearle's**, not Morris's | The three petalled lilies on their stems. Dearle was Morris & Co's chief designer after Morris; he died in 1932, so it left copyright in 2003 under life plus seventy, against 1967 for Morris's own |

**Two of these designs have birds in them and neither one's birds are drawn, and that is
not a rights question.** Trellis's are Philip Webb's, who died in 1915, so they left
copyright in 1985 under life plus seventy and in 2015 under the longest term anywhere;
Strawberry Thief's are Morris's own and are out of copyright with everything else of his.
They are absent because **this engine has no figurative motif**: it grows leaves, petals and
berries along curves and stamps them at chosen points, and a bird is neither. Saying it any
other way puts a date where a reader takes it to be doing work it is not.

Morris died in 1896, so everything of his is long out of copyright, and Dearle in 1932.
**A modern reproduction of one of these is a different question**, which is why nothing here
is traced: a high resolution scan is usually a museum's photograph published under the
museum's own terms, and "it is a Morris" is not on its own a licence for the image somebody
made of it. What is reproduced here is a description, written from the designs, and it is in
`frontend/src/theme/patterns.ts` for anybody to read.

Naming a design by the name its author gave it is nominative use in its strongest form:
these are the historical titles, used as such by the V&A and in every scholarly catalogue,
and there is no alternative name for Strawberry Thief.

> The Morris pattern names identify the historical designs the drawings are after. This
> project is not affiliated with, or endorsed by, Morris & Co.

The other eight are named for the traditions rather than for any surviving work. Every one
of those names is a common noun for a kind of pattern, owned by nobody, and every one of the
patterns is a geometric construction rather than a work: there is no author to have held a
copyright in a rule for setting out circles on a lattice.

| Name | Tradition | What is reproduced |
|---|---|---|
| Nonpareil | European and Turkish marbling, described under that name by Woolnough, 1853 | The comb drawn once through the bath in a single pass |
| Curl | The same tradition, also called snail or French curl | The same comb, worked a second time with a stylus drawn in circles, which carries the lines round each eye |
| Seigaiha | Japanese, the "blue sea wave", in use since the Heian period | Interlocked fans of concentric arcs |
| Asanoha | Japanese, the "hemp leaf" | The hexagonal lattice and the six spokes that make its star |
| Shippo | Japanese, the "seven treasures", also read as linked coins | Circles on a square lattice at the radius that makes each pass through its neighbours' centres |
| Meander | Greek, from the geometric period | The fret, laid as a field rather than as a border |
| Plait | Insular manuscript ornament | The interlace, over and under |
| Khatam | Persian marquetry | The eight point star field and the cross between four stars |

Three of those names were chosen against an obvious alternative. **Khatam, not girih**:
girih names the five-tile quasi-periodic system, which has no square repeat, and calling a
periodic eight-point star field girih is wrong in the one way a reader who knows the field
notices immediately. **Plait, not Book of Kells**: a plait is the construction, and naming a
specific manuscript would claim a resemblance to a particular page that nothing here is
traced from. **Meander, not Greek key**: the two name the same ornament, and the first is
what the literature uses.

No pattern in this app is traced from an image. Every one is generated from a described
rule, and the rule is in the source.

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
| Kanagawa | 4/9 | 6/8 | 9 |
| Tokyo Night | 5/5 | 6/6 | 1 |
| Ayu | 6/6 | 4/4 | 2 |

Nord and Tokyo Night are the two palettes that need no neutral correction in either mode,
which is not luck: both put their neutrals further apart than anybody else does. Kanagawa is
the other end of that, and for the opposite reason: Lotus is ink on a cream page rather than
on a white one, so its whole ink half starts closer to its own background than any other
light member's does. Solarized needs the most, because its
ink tiers are compressed against this app's (base01 through base1 span 2.4 to 4.9 on its own
dark card, where the contract wants 3.0 to 7.0).

## Every correction

**A semantic ink in light is corrected against the page, not the card.** In light the page
is darker than the card, so it is the harder of the two surfaces, and a `500` bisected to
4.5 lands there. Measured across all twenty of them, ten palettes times `bloom` and
`danger`: **4.50 (Solarized) to 4.53 (Everforest) on the page**, and 4.64 (Ayu) to 5.22
(Tokyo Night) on the card. Every row below names the page and quotes the page figure.

**Eight rows used to name the card and quote the card figure**, on Rose Pine, Solarized,
Everforest and Nord, and they were corrected here rather than left as they were: the
correction each of them describes was driven by the page, so the surface was wrong and the
number with it. Gruvbox looks like it belongs in that list and does not, because none of
its corrections is a semantic ink. What stops the class returning is
`palettes.test.ts::the correction tables in docs/theming.md`, which recomputes every "Was"
figure in this section from the upstream hex beside it against the surface the last column
names, and checks every "Shipped" hex against the stylesheet.

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
| `bloom-500` | `#d7827e` | `#a95957` | 2.60 | 4.5 | text on the page |
| `danger-500` | `#b4637a` | `#a7586f` | 3.84 | 4.5 | text on the page |

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
| `bloom-500` | `#d33682` | `#c82a78` | 3.95 | 4.5 | text on the page |
| `danger-500` | `#dc322f` | `#d22626` | 4.02 | 4.5 | text on the page |

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
| `bloom-500` | `#df69ba` | `#b24192` | 2.67 | 4.5 | text on the page |
| `danger-500` | `#f85552` | `#cf2b30` | 2.86 | 4.5 | text on the page |

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
| `bloom-500` | `#b48ead` | `#815e7c` | 2.33 | 4.5 | text on the page |
| `danger-500` | `#bf616a` | `#a84c55` | 3.36 | 4.5 | text on the page |

### Nord, dark

2 corrections.

| Rung | Upstream | Shipped | Was | Needed | Where it is read |
|---|---|---|---|---|---|
| `bloom-500` | `#b48ead` | `#c8a2c1` | 3.55 | 4.5 | text on the card |
| `danger-500` | `#bf616a` | `#f59199` | 2.46 | 4.5 | text on the card |

### Kanagawa, Lotus

7 corrections, the most of any light member.

| Rung | Upstream | Shipped | Was | Needed | Where it is read |
|---|---|---|---|---|---|
| `paper-400` | `#a09cac` | `#888594` | 2.23 | 3.0 | on the card |
| `paper-500` | `#8a8980` | `#6b6a62` | 2.93 | 4.5 | on the card |
| `paper-600` | `#716e61` | `#5f5c52` | 4.26 | 4.5 | on the card |
| `paper-800` | `#545464` | `#504f5f` | 5.00 | 5.39 | on the sunken tier |
| `paper-900` | `#43436c` | `#414169` | 6.78 | 7.0 | on the page |
| `bloom-500` | `#b35b79` | `#994563` | 3.26 | 4.5 | text on the page |
| `danger-500` | `#c84053` | `#b42d44` | 3.55 | 4.5 | text on the page |

`paper-800` is the one rung here corrected against something other than a floor in the rung
contract. It clears every pair it is in at `#545464`; what it does not clear is the badge
value cell, `paper-800` on `paper-100`, whose worst across the palettes is a figure
`docs/decisions.md` states and `palettes.test.ts` asserts. Lotus's sunken tier is a cream
rather than a near white, so at the published ink that pairing lands at 5.00 and takes the
documented worst off Catppuccin at 5.34.

### Kanagawa, Wave

2 corrections.

| Rung | Upstream | Shipped | Was | Needed | Where it is read |
|---|---|---|---|---|---|
| `paper-500` | `#938aa9` | `#968dac` | 4.34 | 4.5 | on the card |
| `paper-600` | `#727169` | `#75746b` | 2.88 | 3.0 | on the card |

### Tokyo Night, light

1 correction, and no neutral moves in either mode.

| Rung | Upstream | Shipped | Was | Needed | Where it is read |
|---|---|---|---|---|---|
| `bloom-600` | `#7b43ba` | `#7940b6` | 4.40 | 4.5 | text on the page |

The page is what moved it, not the card. Tokyo Night Light's page is its side bar,
`#d6d8df`, which is 5.3 CIE L* below its editor background, so a colour that clears 4.5 on
the card at 5.07 and on its own tint at 5.25 can still fail the page. It is the one palette
here whose two surfaces are far enough apart for those three to disagree.

### Tokyo Night, dark

No corrections.

### Ayu, Light

2 corrections.

| Rung | Upstream | Shipped | Was | Needed | Where it is read |
|---|---|---|---|---|---|
| `bloom-500` | `#a37acc` | `#8961b1` | 3.21 | 4.5 | text on the page |
| `danger-500` | `#e65050` | `#d13b3f` | 3.54 | 4.5 | text on the page |

Ayu Light's neutrals are all kept, and that is a placement rather than luck. Its editor
foreground measures 6.10 on its own card, which holds `paper-700` and not the 7.0 body text
asks of `paper-900`, so it sits at 700 and the two rungs below it are generated. Placed at
900 and corrected instead, it would have cleared the floor and squeezed `paper-700` through
`paper-950` into a tenth of the ramp, leaving muted, secondary and body text within 0.02
OKLab lightness of each other.

### Ayu, Dark

No corrections.

Ayu Dark publishes three surfaces, `surface.base`, `surface.lift` and `editor.line`, and
only the first two are taken. All three sit inside **4.61 CIE L***, so a ladder built from
all of them puts the 1px divider this app draws between `paper-800` and `paper-900` at
**3.02 L***,
under the 4.0 floor the badge hairline is anchored to and below the 4.25 that was the
faintest divider anything here shipped. The two rungs that name the page and the card are
published; the two above them are generated, and the divider then measures 8.33.

## The measured result

Every theme and mode clears every pair. `frontend/tests/theme/palettes.test.ts` reads the
shipped stylesheets, resolves the cascade the way a browser does, and asserts the full list;
these are the headline rows, read off the same files by the same formula.

**Four decimals where a cell is within a hundredth of its floor**, two everywhere else. A
figure printed as `7.00` is the one a reader most needs to know the side of, and `7.00`
cannot tell 7.0032 from 6.9968. Landing on a floor is the method working rather than a
risk: a corrected rung is bisected to the floor itself, so the tightest margins here belong
to the palettes that shipped first, Rose Pine's dark `paper-600` at 3.0001 and Endpaper's
light `paper-400` at 3.0003. What holds them is not the margin, it is that
`palettes.test.ts` asserts the whole list against the shipped files on every run.

### Light

| pair | floor | endpaper | catppuccin | rosepine | gruvbox | solarized | everforest | nord | kanagawa | tokyonight | ayu |
|---|---|---|---|---|---|---|---|---|---|---|---|
| body on the page | 7.0 | 16.78 | 7.0019 | 7.06 | 10.22 | 11.31 | 10.06 | 8.26 | 7.0032 | 7.70 | 9.63 |
| secondary on the card | 6.0 | 9.18 | 6.04 | 6.0071 | 6.0011 | 6.05 | 6.0071 | 6.40 | 6.06 | 6.53 | 6.10 |
| muted on the page | 4.5 | 5.67 | 4.92 | 4.78 | 5.03 | 4.81 | 4.73 | 5.02 | 4.87 | 4.98 | 5.09 |
| paper-500 on the card | 4.5 | 4.53 | 4.54 | 4.53 | 4.53 | 4.53 | 4.53 | 4.5075 | 4.53 | 5.11 | 4.55 |
| paper-400 on the card | 3.0 | 3.0003 | 3.0034 | 3.0014 | 3.02 | 3.02 | 3.0015 | 3.0030 | 3.0019 | 3.86 | 3.24 |
| link on the card | 4.5 | 5.47 | 6.11 | 7.76 | 6.25 | 6.88 | 6.58 | 6.34 | 6.04 | 6.86 | 6.05 |
| fill pairing | 4.5 | 4.78 | 5.14 | 6.11 | 4.99 | 5.53 | 5.18 | 5.41 | 5.51 | 6.77 | 4.62 |
| hover pairing | 4.5 | 5.47 | 6.91 | 8.06 | 6.88 | 7.42 | 7.09 | 7.31 | 7.25 | 8.47 | 6.21 |
| focus ring on the page | 3.0 | 3.09 | 3.08 | 3.96 | 3.25 | 3.62 | 3.36 | 3.31 | 3.0067 | 3.35 | 3.01 |
| bloom ink on its tint | 4.5 | 6.69 | 7.79 | 7.41 | 7.54 | 7.73 | 7.66 | 7.33 | 7.29 | 7.53 | 7.31 |
| danger text on the card | 4.5 | 6.29 | 6.28 | 5.85 | 4.90 | 6.03 | 5.05 | 5.21 | 5.28 | 5.60 | 5.23 |

### Dark

| pair | floor | endpaper | catppuccin | rosepine | gruvbox | solarized | everforest | nord | kanagawa | tokyonight | ayu |
|---|---|---|---|---|---|---|---|---|---|---|---|
| body on the page | 8.5 | 15.34 | 11.34 | 11.86 | 10.75 | 12.25 | 8.62 | 10.26 | 11.26 | 11.14 | 10.12 |
| body on the card | 7.0 | 13.94 | 8.69 | 10.90 | 8.45 | 10.61 | 7.38 | 8.26 | 9.75 | 10.59 | 9.81 |
| muted on the card | 6.0 | 7.43 | 6.03 | 6.0004 | 6.0088 | 6.03 | 6.0073 | 6.04 | 6.14 | 6.89 | 6.32 |
| paper-500 on the card | 4.5 | 4.56 | 4.5096 | 4.52 | 4.54 | 4.51 | 4.51 | 4.5028 | 4.51 | 5.46 | 4.59 |
| paper-600 on the card | 3.0 | 3.0011 | 3.40 | 3.0001 | 3.16 | 3.0017 | 3.21 | 3.0069 | 3.0084 | 4.18 | 3.15 |
| accent text on the card | 4.5 | 7.51 | 9.07 | 5.24 | 6.43 | 5.31 | 7.14 | 5.59 | 6.36 | 8.27 | 10.92 |
| fill pairing | 4.5 | 5.98 | 11.01 | 5.70 | 7.01 | 4.75 | 7.28 | 5.99 | 5.94 | 7.14 | 9.98 |
| hover pairing | 4.5 | 8.26 | 11.83 | 7.42 | 8.18 | 6.13 | 8.33 | 6.94 | 7.35 | 8.70 | 11.27 |
| focus ring on the page | 3.0 | 5.98 | 11.01 | 4.29 | 7.01 | 4.75 | 7.28 | 5.99 | 5.94 | 7.14 | 9.98 |
| bloom text on the card | 4.5 | 9.25 | 8.23 | 6.55 | 4.72 | 5.92 | 5.40 | 5.63 | 6.83 | 7.39 | 9.34 |
| danger text on the card | 4.5 | 9.25 | 5.43 | 7.96 | 6.01 | 5.92 | 4.76 | 4.80 | 7.07 | 8.46 | 7.16 |

## What the contract does not cover

Three things are outside it, and all three are real. They are recorded here
rather than left to be discovered, because a contract that is silent about its
own edges reads as a contract that has none.

**`warn`, `ok` and `loan` are not tokens.** Amber, green and orange are still
raw Tailwind at 29 lines across 16 files, so nine of the ten palettes ship an
overdue badge and a caution banner in colours that belong to none of them.
Tokenising them is three ramps times ten palettes times two modes, which is
its own piece of work. Most of those pairings are self-contained
(`bg-amber-50` with `text-amber-800`), which is why nothing here fails and also
why nothing here catches them.

One was not self-contained and is repaired: `text-green-600` on the card, the
success message on four screens, measured **2.61 (Tokyo Night) to 3.22
(Endpaper)** against a floor of 4.5. It is now `text-green-800`, which clears on
every palette at **5.78 (Tokyo Night) to 7.13 (Endpaper)**. `green-700` looks
like the answer and is not: it is under the floor on five of the ten, at 4.01 on
Tokyo Night, 4.12 on Kanagawa, 4.29 on Nord, 4.37 on Catppuccin and 4.49 on
Gruvbox. A fixed hue is a bet on ten different card colours at once, and that is
the argument for the token job rather than for more repairs like this one.

Three palettes were added after that repair and it held: the darkest card of the
ten is now Tokyo Night's rather than Nord's, and `green-800` still clears there
by 1.28.

**Dark hover is covered now.** Twelve sites wrote `hover:text-accent-800` with
no `dark:` variant and measured **1.36 to 2.85** on the dark card: legible at
rest, illegible while pointed at. All twelve are repaired, and
`frontend/tests/houseRules.test.ts` holds the rule with no exemption list.

**The effort is still inverted in one place.** `paper-500` is held to 4.5 in
all twenty theme-modes and painted at **zero** call sites, while the amber
and orange above are painted constantly and measured nowhere.

## What this does to the wallpaper

The wallpaper's ink is read off `accent-700` and `bloom-700` in light, and
`accent-300` and `bloom-300` in dark, so it follows the palette without any
file that draws a tile knowing a hex. The page is read with them, off
`paper-50` and `paper-950`, because that is what the ink is weighed against.

**The opacity is solved, not written down.** A layer states a weight, as an
OKLab lightness delta over the page, and `wallpaperWeights` bisects for the
alpha that reaches it:

```
light   ground 0.026   under 0.033   foliage 0.042   bloom 0.057
dark    ground 0.061   under 0.070   foliage 0.083   bloom 0.102
```

It has to work that way. At a fixed alpha the weight is a function of the
palette, and the spread was the width of the whole budget, measured across the
seven palettes that shipped when the solve was built:

| | at one alpha | solved per palette |
|---|---|---|
| light, spread of the tile's weight | 1.27x | **1.052x** |
| dark | 1.32x | **1.030x** |
| light, in continuous colour | | 1.002x |

The residual is the compositor rounding the blend to 8 bits per channel, not
the palette: in continuous colour those seven agree to the bisection's own
precision. Across the ten the alpha the dark ground needs runs **0.0720 (Ayu)
to 0.1093 (Rose Pine)** to hold that one weight, and the highest solve anywhere
is still Solarized dark's bloom at **0.2082**, which is what the 0.30 ceiling is
set against.

Two things follow for whoever adds a palette, and the three added after this was
written are the evidence for the first. Nothing in `patterns.ts` needs touching:
the eleventh palette's wallpaper is solved from its own tokens, and the tenth's
was. And the guard on opacity is 0.30 rather than 0.15, because 0.15 was a
ceiling in the wrong unit: seven of the ten palettes need more than 0.15
somewhere in dark, where five of seven did. The ceiling on how heavy a tile may
look is the table above.

## The sixteen wallpapers

Two families, which is how the picker groups them.

| William Morris | Decorated papers |
|---|---|
| Trellis, Jasmine, Acanthus, Marigold, Pimpernel, Strawberry Thief, Willow Bough, Golden Lily | Nonpareil, Curl, Seigaiha, Asanoha, Shippo, Meander, Plait, Khatam |

The Morris eight are grown along curves; the papers are set out on a lattice.
Between them they need both halves of the engine, which is the reason to have
both. What each reproduces, and on what basis, is in **The wallpaper names**
above.

### The ink budget

Mean tile weight, the same number in every palette by construction:

| | | | |
|---|---|---|---|
| shippo 0.00772 | jasmine 0.00778 | meander 0.00783 | nonpareil 0.00784 |
| pimpernel 0.00788 | curl 0.00804 | seigaiha 0.00805 | asanoha 0.00806 |
| acanthus 0.00815 | khatam 0.00818 | trellis 0.00820 | plait 0.00822 |
| lily 0.00855 | willow 0.00868 | marigold 0.00869 | strawberry 0.00879 |

The band is 0.0070 to 0.0092 and it binds at both ends. The spread across the
sixteen is **1.138x**, against 2.65x for the five that shipped before, and five
tiles moved to get there: Willow was 0.00485 and gained an underfoliage plane,
Golden Lily was 0.01343 and its petals came down from 1.2 to 0.85, Trellis was
0.01030 and almost all of the excess was its roses, Jasmine arrived at 0.00482,
thin in both of its planes because it is a trail over a ground, and Marigold
arrived at 0.00678 with heads less than half the size Pimpernel's blooms are.

Marigold then moved twice more and neither time was for this band: it was
rebuilt onto the repeat's second mirror axis to close a 68px band of empty
columns, 0.00777 to 0.00846, and its cross link was arched rather than left
nearly straight, 0.00846 to 0.00869.

The spread is a property of the measure as well as of the tiles. Coverage is
computed analytically, which double counts ink laid twice on one pixel and
misses the cap on a stroke, so against the same tiles rasterised the numbers
run 17.7% heavy on Golden Lily and 12.7% light on Nonpareil, and the spread is
1.235x. Every tile is inside the band under either measure. Budgeting from the
rasterised field is the better instrument and is a retune rather than an edit.

### The admission rule

A pattern ships only if its defining feature is discriminable at true opacity
and native scale. Two numbers, both read off the generated tile:

- **Tint contrast at least 0.196.** The tile's ink blurred to the acuity the
  rule names, as RMS contrast against its own mean. The floor is what a field
  of parallel lines at exactly the 12px mark pitch and 2.4px wide measures; a
  4px, 1.2px field measures 0.018 and a 30px, 3px one 1.140. The sixteen run
  0.354 (Nonpareil) to 1.696 (Pimpernel). Those three are calibration
  measurements rather than a formula, each one is a pitch **and** a stroke
  width, and `rasterise.ts` says why that distinction is load bearing. The
  first two are now asserted in `patterns.test.ts`, so the filter cannot move
  under the floor without something failing.

  **A high score here is not a good tile.** The measure is contrast against the
  tile's own mean, so a void raises it: Marigold scored the highest of the
  sixteen while carrying a 68px band of empty columns, and reads 1.526 with the
  band gone. Neither this nor peak coverage can see an empty region.

- **No empty row or column, for a Morris repeat.** The third measure, and the
  one that catches a void. It is asserted at zero and only for that family,
  which is what leaves it with no free parameter: every gap of the kind in the
  shipped set is a paper's own mark pitch, Meander and Curl at 11px, and no
  repeat grown along curves has one at all. A threshold in pixels is not
  available, and the tempting one is wrong: the 12px acuity pitch governs the
  gap between adjacent marks, so a field of parallel lines at a 16px pitch
  measures 0.488 on the tint rule, two and a half times its floor, and still
  leaves a 12px run.
- **Peak coverage at least 0.9 per layer.** Somewhere the layer has to lay down
  a whole mark. A pattern of sub-pixel hairlines has structure and no weight,
  and that is a stroke-width problem rather than an opacity one.

This is what refused a woven girih and respecified the khatam as a flat field
at an 80px pitch. Full reasoning, including the filter that had to be thrown
away, is in [decisions.md](decisions.md).

### Adding a wallpaper

1. Build it in `patterns.ts`, from the primitives if they fit: `lattice`,
   `radial`, `ribbon`, `flow` and `mirror`, plus `grow` for anything that
   follows a curve.
2. Anything that varies with position must be periodic in the tile. `lattice`,
   `flow` and `swirl` all throw rather than let it through. `swirl`'s condition
   is the one worth reading before using it: a displacement field built from
   terms that vanish outside a radius repeats with the tile exactly when no two
   of those terms overlap, so it refuses centres closer than twice the reach.
3. Run `bun run test tests/theme/patterns.test.ts`. It measures the budget, the
   admission rule, the byte cap and the interning, and it names the pattern and
   the number in every failure.

## Choosing one

`/settings/appearance/theme`, its own route and a child of the Appearance settings screen,
which keeps a summary and a link.

The reason for a route rather than a section or a dialog is the design's own: **the only
honest preview of a wallpaper is the page.** The pattern is painted on `body`, so the picker
is the app surface with the controls laid over it, every choice applies the moment it is
made, and there is no Save button. The preview on top of it is the reader's **own first two
book cards**, read out of the query cache and never fetched, because invented sample content
is not the real page. An empty cache gets a sentence rather than a placeholder book.

Four controls, in this order:

| Control | What it holds |
|---|---|
| Preview | Two of the reader's own books, live |
| Light and dark | Light, Dark, Follow system |
| Palette | Ten tiles, each drawn in its own colours, with the attribution and any constructed member |
| Wallpaper | None, Surprise me, then the sixteen under **William Morris** and **Decorated papers** |

Plus the licences, on the screen that offers the things they cover.

### None is a tile, not a switch

`wallpaper` already answered two questions, which pattern and Surprise me, so off is a
third value in it (`WALLPAPER_OFF`) rather than a boolean beside it that could disagree with
it. It is the one id `patternFor` does not degrade to a random pattern: an off that came
back as a wallpaper would be a choice the app declined to keep.

**Two off states, and the picker distinguishes them.** A chosen off is `pattern === null`;
the system asking for more contrast is `wallpaperOff`. Both clear the body, only the second
is worth explaining, and the reader's own choice stays marked underneath the explanation
because it is what comes back when the system stops asking.

### The swatches restate nothing

A palette tile draws that palette's page, card, ink, accent and bloom, and none of the
thirty five values is a hex in TypeScript. `readPaletteColours` puts each palette on the
document in turn and reads the computed properties back, the same way `wallpaperColours`
resolves the wallpaper's ink. `withPalette` wraps the swap and restores the attribute in a
`finally`; the read runs from a layout effect, so no intermediate state is ever painted.

`withPalette` is load bearing for a second reason. A child's effect runs before its
parent's, so a component that read the document after asking for a palette change would read
the palette before it and show a grid one choice behind.

`ThemeProvider` applies the appearance from a layout effect for the same reason it reads
from one. As a passive effect it ran after the browser had painted, so every change made
with the page open showed one frame of the previous look.

**The wallpaper tiles are drawn at true opacity.** A swatch at three times the page's
opacity is a lie about what is being chosen. The honest answer to a faint swatch is a bigger
one: `background-size: contain`, four columns inside `max-w-6xl` less the page's padding and
the section's, is a 257px cell against tiles that repeat at 240px to 300px, so nine of the
ten are drawn at 86% to 107% of the size they have on the page. Asanoha, at 420px, shrinks
to 61%.

### The front door

A device with nobody signed in on it paints Endpaper, the system's mode, and **Willow Bough,
fixed**. Not Surprise me, which is what a new *account* starts at: `readCachedAppearance`
returns the fixed look when no account is named and the cache is empty, and the account
default when one is.

The login screen "decides whether the app looks made or assembled", and a front door that is
a different pattern every visit reads as a slot machine. Randomness is a pleasure once you
are inside. An admin-set login image, where one is set, covers it anyway.

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
Endpaper and be silently ignored on the other nine.

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

**Dracula** was measured and not shipped, and that is not a data change waiting to happen:
its ramp needs eight of twelve neutrals generated, and its light member, Alucard, exists
only inside a commercial product, so there is no published light theme to port and no Nord
style construction out of published groups either.

**Kanagawa** was on that list for the other reason, that its light values could not be
verified against upstream at the time, and it now ships. They are in
`lua/kanagawa/colors.lua`, which names every colour, and `lua/kanagawa/themes.lua`, which
says which name plays which role in Lotus and in Wave: the `bg`, `bg_m1`, `bg_m2` and
`bg_m3` ladder is the surface order, and `ui.fg` and `ui.fg_dim` are the two inks. A palette
that publishes its roles as well as its hexes is the easy case, and the reason this one
looked hard is that the roles are in a second file.

**Two more were checked and refused while these three were chosen**, and both refusals are
about something other than the colours. `folke/tokyonight.nvim` and `ayu-theme/ayu-vim` are
**Apache 2.0**, and each is the repository a search returns first for a palette whose MIT
source is somewhere else. **Flexoki** is MIT and publishes both modes and a full ramp, which
would have made it the cheapest of the four to port, and it is refused on measurement: its
dark page is **0.6** OKLab dE from Endpaper's and its light card **1.9** from Endpaper's, so
the tile a reader would be choosing is the one the app already opens on.

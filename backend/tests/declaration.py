"""Whether a file declares itself internal, answered the way the publish gate answers it.

**The gate owns the rule; this is the one Python copy of it.** A file the mirror
strips carries `SENTENCE` in its opening lines, and the gate refuses to publish
any file that does. A published module may not read the gate's script, so the
rule is spelled here, and every Python reader in this tree asks here.

**Spelled for the engine the pipeline runs, which is busybox `grep -E` on musl**,
reading the first `HEADER_LINES` lines that `head -n` writes. Each clause below
is what that engine does, measured in the pipeline's own image rather than taken
from POSIX or from this machine's `grep`:

* **Characters, not bytes, in the prefix bound.** musl reads UTF-8 with no
  locale set, so `> ⚠️ ` is five characters and inside the bound.
* **A line is what a newline ends**, never a carriage return or a separator,
  so the file is split as bytes, and decoding happens after.
* **`[[:space:]]` is musl's own set**, which takes some Unicode spaces and not
  others, the no break space among the refused.
* **A byte that is not UTF-8 defeats the match** in the prefix or as the
  character straight after the closing `**`; anywhere further along the line it
  does not matter.
* **A NUL starts a fresh match**, as a line break would.

**What pins it is a guard outside the published tree**, which runs the gate's own
pattern and window through that engine over shapes for each clause, among them
one per candidate space and one on each side of the window's end, and compares
each answer with this one. In the mirror, which carries no gate, nothing does.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Final

#: The declaration, for fixtures that plant one.
SENTENCE: Final = "**This file is internal.**"

#: The opening lines a declaration has to sit in.
HEADER_LINES: Final = 30

#: musl's `iswspace`, which is what `[[:space:]]` reads there. Escaped so its
#: gap at the figure space, U+2007, can be seen: musl refuses that one.
_SPACE = " \t\n\v\f\r\x85\u2000-\u2006\u2008-\u200a\u2028\u2029\u205f\u3000"

#: The code points `surrogateescape` decodes a byte that is not UTF-8 into.
_UNDECODABLE = "\udc80-\udcff"

_DECLARATION: Final = re.compile(
    rf"[^A-Za-z0-9{_UNDECODABLE}]{{0,6}}[{_SPACE}]*"
    rf"{re.escape(SENTENCE)}(?![{_UNDECODABLE}])"
)


def declares(data: bytes) -> bool:
    """Whether `data`, a whole file's bytes, carries the declaration in its header."""
    return any(
        _DECLARATION.match(start)
        for line in data.split(b"\n")[:HEADER_LINES]
        for start in line.decode("utf-8", "surrogateescape").split("\0")
    )


def declares_itself_internal(path: Path) -> bool:
    """Whether the file at `path` declares itself internal. Unreadable is no."""
    try:
        return declares(path.read_bytes())
    except OSError:
        return False

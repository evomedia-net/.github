"""Render this repository's prose markdown to plain-text twins.

The .txt files exist because markdown renders in only some of the places these
documents get read. GitHub renders it when browsing a file but shows raw markup
in diffs and review; editors, pagers and `type`/`cat` show raw markup always.
Plain text opens in anything with no configuration, and is the form LLM
ingestion prefers - the same reason llms.txt exists.

They are generated - never edit one by hand:

    python scripts/plaintext_twins.py          # rewrite every twin
    python scripts/plaintext_twins.py --check  # exit 1 if any is out of sync

Nothing in this repository runs --check automatically: it has no test suite
and no CI. Run it by hand before committing a documentation change, until
there is somewhere for the check to live.

A hand-kept duplicate drifts, and the drift is invisible precisely because
nobody reads both copies. The twins this repository had before were written by
hand, and had already drifted: the fleet format underlines a third-level
heading with "~", and they used "-".

The format is evo.polaris's CHANGELOG.txt, which is the fleet's reference: h1
"=", h2 "-", h3 "~", links as "text (url)", code fences dropped with their
contents indented, inline markup removed, tables left as they are.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

#: "all"   - every tracked prose .md owes a twin.
#: "adopt" - only the files that already have one, plus the changelog. For a
#:           repository whose docs folder is a large archive of historical
#:           plans, where twinning everything would generate scores of files
#:           nobody asked for; the choice of which of those are still prose
#:           worth mirroring is a decision for a person, not for a rollout.
MODE = "all"

#: Directory names that hold no prose of ours. Tracked third-party READMEs are
#: the reason `vendor` is here: a twin beside a vendored file would be our
#: edit to someone else's package. `.github` holds issue and pull-request
#: templates, which are markup nobody reads straight through.
SKIP_DIRS = frozenset({".github", "vendor", "third_party", "node_modules"})

#: Markdown that is machinery rather than prose, named as exempt by the
#: convention itself.
EXEMPT_NAMES = frozenset({"CLAUDE.md", "AGENTS.md"})


def _tracked_markdown() -> list[Path]:
    """Every .md git knows about, repo-relative.

    Asked of git rather than of the filesystem. A walk finds build output,
    virtualenvs, `node_modules` and whatever scratch file someone left in the
    working tree, and would then demand a twin for each; git already knows
    which files are ours. It also means a gitignored Claude Code worktree -
    a complete second copy of the repository - cannot be walked into.
    """
    try:
        done = subprocess.run(
            ["git", "-C", str(ROOT), "ls-files", "-z", "--", "*.md"],
            capture_output=True, text=True, check=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        print(f"cannot list tracked files: {exc}", file=sys.stderr)
        raise SystemExit(1)
    return [Path(p) for p in done.stdout.split("\0") if p]


def pairs() -> tuple[tuple[Path, Path], ...]:
    """Every prose markdown file, with the twin it owes.

    Discovered rather than listed. A hand-kept list and the act of adding a
    document are two separate acts, and the second is the one that gets
    skipped; discovery makes them one act.
    """
    found: list[tuple[Path, Path]] = []
    for md in sorted(_tracked_markdown()):
        if md.name in EXEMPT_NAMES or set(md.parts[:-1]) & SKIP_DIRS:
            continue
        twin = md.with_suffix(".txt")
        if MODE == "adopt" and md.name != "CHANGELOG.md" and not (ROOT / twin).exists():
            continue
        found.append((md, twin))
    return tuple(found)


#: HTML element names, so a tag can be told from prose that merely looks like
#: one. An allowlist and not `</?\w+>`, because these documents are full of
#: placeholders written the same way - `<owner>/<repo>.git`, `<subject>.txt` -
#: and deleting those would take words out of the twin, which is the one thing
#: it must never do.
_HTML = (
    r"</?(?:picture|source|img|div|span|br|p|a|table|thead|tbody|tfoot|tr|td|th"
    r"|details|summary|sup|sub|kbd|em|strong|code|pre|hr|h[1-6]|ul|ol|li"
    r"|blockquote|center|figure|figcaption|video|audio|iframe|small|b|i|u|s)"
    r"(?:\s[^<>]*)?/?>"
)


def _inline(text: str) -> str:
    """Strip the inline markup, keeping the words and the link targets.

    Inline code is lifted out FIRST and put back last. What is inside backticks
    is content, not markup, and running the emphasis rules over it corrupts it:
    DocketMail documents a pair of input files as `Civil Parties*JWEB*.txt`, and
    stripping that glob's asterisks as italics glued two words into
    "PartiesJWEB". The same ordering bug is in the fleet's other two twin
    generators. Same reasoning for the HTML rules - `<div>` written as an
    example is a word, not a tag.
    """
    code: list[str] = []

    def lift(match: re.Match) -> str:
        code.append(match.group(1))
        return f"\x00{len(code) - 1}\x00"

    def restore(s: str) -> str:
        return re.sub(r"\x00(\d+)\x00", lambda m: code[int(m.group(1))], s)

    text = re.sub(r"`([^`]+)`", lift, text)

    # An <img> carries its words in alt=, exactly as a markdown image does.
    text = re.sub(r"<img\b[^<>]*?\balt=[\"']([^\"']*)[\"'][^<>]*>", r"\1", text)
    text = re.sub(_HTML, "", text)
    text = re.sub(r"!\[([^\]]*)\]\([^)]*\)", r"\1", text)  # images -> alt text

    def link(match: re.Match) -> str:
        """A link becomes "text (url)" - unless the text already IS the url.

        `dev@evomedia.net` linked to mailto:dev@evomedia.net, or a filename
        linked to itself, would otherwise read as "x (x)", which tells the
        reader nothing twice. Compared after putting the code back, because
        such a link is usually written with backticks around its text.
        """
        shown, url = match.group(1), match.group(2)
        bare, target = restore(shown), restore(url)
        if bare == target or target == "mailto:" + bare:
            return shown
        return f"{shown} ({url})"

    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", link, text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"\1", text)  # bold
    text = re.sub(r"(?<!\*)\*([^*\n]+)\*(?!\*)", r"\1", text)  # italic
    return restore(text)


def render(md: str) -> str:
    out: list[str] = []
    in_fence = False
    for line in md.splitlines():
        if line.lstrip().startswith("```"):
            # Drop the fence markers; the code itself stays, indented so it
            # still reads as a block without the backticks.
            in_fence = not in_fence
            continue
        if in_fence:
            out.append(("    " + line) if line else "")
            continue
        # An HTML comment is invisible in rendered markdown, but its markers
        # are not invisible in a text file - they read as stray punctuation.
        # Keep what the comment says, drop the <!-- --> around it.
        if line.strip() in ("<!--", "-->"):
            continue
        heading = re.match(r"^(#{1,6})\s+(.*)$", line)
        if heading:
            text = _inline(heading.group(2))
            out.append(text)
            out.append("=-~..."[len(heading.group(1)) - 1] * len(text))
            continue
        rendered = _inline(line)
        # A line that was only a tag - <picture>, </picture>, a bare <source> -
        # leaves nothing behind. Emitting the blank would turn one HTML block
        # into a run of empty lines in the middle of a paragraph.
        if line.strip() and not rendered.strip():
            continue
        out.append(rendered)
    text = "\n".join(out)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip() + "\n"


def main() -> int:
    check = "--check" in sys.argv
    found = pairs()
    if not found:
        print("no prose markdown found - the discovery is wrong, not the repo")
        return 1

    stale: list[str] = []
    for md_name, txt_name in found:
        rendered = render((ROOT / md_name).read_text(encoding="utf-8-sig"))
        target = ROOT / txt_name
        if check:
            current = target.read_text(encoding="utf-8-sig") if target.exists() else ""
            # Compared with the line endings normalised. The working tree is
            # CRLF on Windows and the repository is LF, and a tool that edits a
            # twin in place (zbump rolls the changelog's Unreleased heading at
            # release time, writing [Environment]::NewLine) leaves CRLF inside
            # a file this writes as LF. git removes that difference on commit,
            # so a byte comparison would fail over something that never
            # reaches the repository.
            if current.replace("\r\n", "\n") != rendered:
                stale.append(str(txt_name))
            continue
        target.write_text(rendered, encoding="utf-8", newline="\n")
        print(f"Wrote {txt_name} ({len(rendered.splitlines())} lines)")

    if check:
        if stale:
            print("out of sync: " + ", ".join(stale)
                  + " - run: python scripts/plaintext_twins.py")
            return 1
        print(f"in sync: {len(found)} pair(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

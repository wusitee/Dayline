"""A small Markdown subset rendered as escaped GTK label markup."""

import re
from html import escape

from dayline.agenda import link_markup
from dayline.errors import DaylineError

_INLINE = re.compile(
    r"(?P<code>`[^`\n]+`)"
    r"|(?P<link>\[(?P<label>[^\]\n]+)\]\((?P<url>(?:[^()\s]|\([^()\s]*\))+)\))"
    r"|(?P<bare>https?://[^\s<>\"']+)"
    r"|(?P<strong>\*\*(?=\S).+?(?<=\S)\*\*|(?<!\w)__(?=\S).+?(?<=\S)__(?!\w))"
    r"|(?P<emphasis>(?<!\w)\*(?=\S)[^*\n]+?(?<=\S)\*(?!\w)"
    r"|(?<!\w)_(?=\S)[^_\n]+?(?<=\S)_(?!\w))"
    r"|(?P<escaped>\\[\\`*_\[\]#>+-])"
)
_HEADING = re.compile(r" {0,3}(#{1,6})\s+(.+?)(?:\s+#+)?\s*$")
_LIST = re.compile(r"(\s*)([-+*]|\d+[.)])\s+(?:\[([ xX])\]\s+)?(.*)")
_FENCE = re.compile(r" {0,3}(`{3,}|~{3,})[^`~]*$")


def _inline(text: str, *, links: bool = True) -> str:
    parts = []
    position = 0
    for match in _INLINE.finditer(text):
        parts.append(escape(text[position : match.start()]))
        token = match.group()
        if match.group("code"):
            parts.append(f"<tt>{escape(token[1:-1])}</tt>")
        elif match.group("link"):
            url = match.group("url")
            if links and re.fullmatch(r"https?://[^\s<>\"']+", url):
                parts.append(
                    f'<a href="{escape(url)}">{_inline(match.group("label"), links=False)}</a>'
                )
            else:
                parts.append(escape(token))
        elif match.group("bare"):
            parts.append(link_markup(token) if links else escape(token))
        elif match.group("strong"):
            parts.append(f"<b>{_inline(token[2:-2], links=links)}</b>")
        elif match.group("emphasis"):
            parts.append(f"<i>{_inline(token[1:-1], links=links)}</i>")
        else:
            parts.append(escape(token[1:]))
        position = match.end()
    parts.append(escape(text[position:]))
    return "".join(parts)


def markdown_markup(text: str, *, checklists: bool = False, hovered: int | None = None) -> str:
    """Render headings, lists, checklists, emphasis, code, and HTTP(S) links.

    Notes stay plain text in storage. HTML and unsupported syntax are literal.
    Optional checklist links identify source lines; they never complete the task.
    """
    parts = []
    fence = None
    code = []
    for index, line in enumerate(text.split("\n")):
        marker = _FENCE.fullmatch(line)
        if fence:
            if line.strip() and set(line.strip()) == {fence[0]} and len(line.strip()) >= len(fence):
                parts.append("<tt>" + escape("\n".join(code)) + "</tt>")
                fence, code = None, []
            else:
                code.append(line)
        elif marker:
            fence = marker[1]
        elif heading := _HEADING.fullmatch(line):
            content = f"<b>{_inline(heading[2])}</b>"
            if len(heading[1]) <= 2:
                size = "x-large" if len(heading[1]) == 1 else "large"
                content = f'<span size="{size}">{content}</span>'
            parts.append(content)
        elif item := _LIST.fullmatch(line):
            indent, bullet, checked, content = item.groups()
            if checked is not None:
                bullet = "☐" if checked == " " else "☑"
                colors = ("#b5b1a9", "#f3c47a") if checked == " " else ("#91c59c", "#c0e7bd")
                bullet = (
                    f'<span foreground="{colors[index == hovered]}" '
                    'underline="none" size="x-large">'
                    f"{bullet}</span>"
                )
                if checklists:
                    bullet = f'<a href="dayline-checklist:{index}">{bullet}</a>'
            elif bullet in "-+*":
                bullet = "•"
            parts.append(f"{indent}{bullet} {_inline(content)}")
        else:
            parts.append(_inline(line))
    if fence:
        parts.append("<tt>" + escape("\n".join(code)) + "</tt>")
    return "\n".join(parts)


def toggle_checklist(text: str, line: int) -> str:
    """Change only the checkbox character of a rendered checklist source line."""
    if f'href="dayline-checklist:{line}"' not in markdown_markup(text, checklists=True):
        raise DaylineError("This checklist changed. Reopen the item before trying again.")
    lines = text.split("\n")
    match = _LIST.fullmatch(lines[line])
    position = match.start(3)
    checked = "x" if match[3] == " " else " "
    lines[line] = lines[line][:position] + checked + lines[line][position + 1 :]
    return "\n".join(lines)

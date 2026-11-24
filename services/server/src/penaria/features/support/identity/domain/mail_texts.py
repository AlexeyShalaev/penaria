"""The texts of the install's emails, in the recipient's language, as plain text and as HTML.

The words live in ``mail_texts/<locale>.json``; the values put into them (names, links) are escaped
in the HTML part. The HTML suits mail clients: one table, inline styles, no images or scripts.
"""

import json
from dataclasses import dataclass
from datetime import timedelta
from functools import cache
from html import escape
from importlib.resources import files
from typing import Any

from penaria.features.support.identity.domain.mail import Content, MailKind
from penaria.features.support.identity.domain.models import LOCALES
from penaria.features.support.identity.domain.permissions import Preset

MINUTES_IN_HOUR = 60
HOURS_IN_DAY = 24
# Below two of a larger unit, a duration is told in the smaller one: "90 minutes", "36 hours".
UNIT_SWITCH = 2
RU_FEW = range(2, 5)
RU_TEENS = range(11, 15)
DECIMAL = 10
HUNDRED = 100


@dataclass(frozen=True, slots=True)
class Link:
    url: str
    # How long it works; the email says so.
    valid_for: timedelta


def compose(kind: MailKind, locale: str, values: dict[str, str], *, server: str, link: Link | None = None) -> Content:
    """The email of ``kind`` in ``locale``, with ``values`` put into its words and ``link`` as its button."""
    texts = _texts(locale)
    mail = texts["mails"][kind.value]
    layout = texts["layout"]
    filled = {**values, "server": server}
    subject = " ".join(mail["subject"].format_map(filled).split())
    title = mail["title"].format_map(filled)
    lead = mail["lead"].format_map(filled)
    notes = [note.format_map(filled) for note in mail["notes"]]
    footer = layout["footer"].format(server=server)
    validity = None if link is None else layout["valid_for"].format(duration=duration(link.valid_for, locale))
    text = _text(title, lead, notes, footer, link, mail.get("action"), validity)
    html = _html(
        locale,
        title=escape(title),
        lead=_escaped(mail["lead"], filled),
        notes=[_escaped(note, filled) for note in mail["notes"]],
        footer=escape(footer),
        link=link,
        action=mail.get("action"),
        validity=validity,
        fallback=layout["fallback"],
    )
    return Content(subject=subject, text=text, html=html)


def role_name(preset: Preset, locale: str) -> str:
    """A preset role as the email names it in ``locale``."""
    return str(_texts(locale)["roles"][preset.value])


def duration(span: timedelta, locale: str) -> str:
    """``span`` in words, in whole minutes, hours or days: "30 minutes", "24 часа", "7 days"."""
    minutes = int(span.total_seconds()) // MINUTES_IN_HOUR
    if minutes < UNIT_SWITCH * MINUTES_IN_HOUR:
        unit, n = "minute", minutes
    elif minutes < UNIT_SWITCH * HOURS_IN_DAY * MINUTES_IN_HOUR:
        unit, n = "hour", minutes // MINUTES_IN_HOUR
    else:
        unit, n = "day", minutes // (MINUTES_IN_HOUR * HOURS_IN_DAY)
    forms = _texts(locale)["layout"]["duration"][unit]
    return str(forms[plural_category(n, locale)]).format(n=n)


def plural_category(n: int, locale: str) -> str:
    """The CLDR plural category of a whole number: English has one and other, Russian one, few and many."""
    if locale == "ru":
        if n % DECIMAL == 1 and n % HUNDRED != RU_TEENS.start:
            return "one"
        if n % DECIMAL in RU_FEW and n % HUNDRED not in RU_TEENS:
            return "few"
        return "many"
    return "one" if n == 1 else "other"


@cache
def _texts(locale: str) -> dict[str, Any]:
    if locale not in LOCALES:
        raise ValueError(f"no email texts in the locale ({locale})")
    loaded: dict[str, Any] = json.loads(files(__package__).joinpath(f"mail_texts/{locale}.json").read_text("utf-8"))
    return loaded


def _escaped(template: str, values: dict[str, str]) -> str:
    return escape(template).format_map({key: escape(value) for key, value in values.items()})


def _text(
    title: str,
    lead: str,
    notes: list[str],
    footer: str,
    link: Link | None,
    action: str | None,
    validity: str | None,
) -> str:
    lines = [title, "", lead]
    if link is not None:
        lines += ["", f"{action}:", link.url]
    if validity is not None:
        lines += ["", validity]
    for note in notes:
        lines += ["", note]
    lines += ["", "--", footer]
    return "\n".join(lines) + "\n"


SANS = "-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,'Helvetica Neue',Arial,sans-serif"
PARAGRAPH = f"margin:0 0 16px;font:15px/22px {SANS};color:#23211e"
MUTED = f"margin:0 0 12px;font:13px/19px {SANS};color:#5b6573"


def _html(
    locale: str,
    *,
    title: str,
    lead: str,
    notes: list[str],
    footer: str,
    link: Link | None,
    action: str | None,
    validity: str | None,
    fallback: str,
) -> str:
    parts = [
        f'<h1 style="margin:0 0 16px;font:600 22px/28px {SANS};color:#23211e">{title}</h1>',
        f'<p style="{PARAGRAPH}">{lead}</p>',
    ]
    if link is not None:
        url = escape(link.url)
        parts += [
            '<p style="margin:24px 0">'
            f'<a href="{url}" style="display:inline-block;padding:12px 20px;border-radius:8px;'
            f'background:#2f7a62;color:#ffffff;font:600 15px/20px {SANS};text-decoration:none">'
            f"{escape(action or '')}</a></p>",
            f'<p style="{MUTED}">{escape(fallback)}<br>'
            f'<a href="{url}" style="color:#2f7a62;word-break:break-all">{url}</a></p>',
        ]
    if validity is not None:
        parts.append(f'<p style="{MUTED}">{escape(validity)}</p>')
    parts += [f'<p style="{MUTED}">{note}</p>' for note in notes]
    body = "".join(parts)
    return (
        f'<!doctype html><html lang="{locale}"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1"><title>'
        f"{title}</title></head>"
        '<body style="margin:0;padding:24px 12px;background:#f6f4ef">'
        '<table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%" '
        'style="max-width:560px;margin:0 auto;background:#ffffff;border:1px solid #e2ddd1;border-radius:12px">'
        f'<tr><td style="padding:28px 28px 8px;font:700 15px/20px {SANS};color:#2f7a62">Penaria</td></tr>'
        f'<tr><td style="padding:8px 28px 12px">{body}</td></tr>'
        f'<tr><td style="padding:16px 28px 24px;border-top:1px solid #e2ddd1;font:12px/18px {SANS};color:#7a8390">'
        f"{footer}</td></tr></table></body></html>"
    )

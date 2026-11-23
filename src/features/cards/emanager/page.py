# One eManager page as read from its HTML: who is logged in, its forms with what a browser would send, its tables.
import re
from dataclasses import dataclass, field
from html.parser import HTMLParser

from features.cards.emanager.window import EfsError


# One form on a page: what the browser would send, and the buttons it offers.
@dataclass
class Form:
    action: str
    fields: dict[str, str] = field(default_factory=dict)
    buttons: dict[str, str] = field(default_factory=dict)


# A page: its address, HTML, logged-in user, forms, and each table's rows of cell texts by the table's id ("" if none).
@dataclass
class Page:
    url: str
    html: str
    user: str
    forms: list[Form]
    rows: dict[str, list[list[str]]]

    # The form that offers a button (and holds these field values, when a page has one such form per row); an error
    # when the page has none, which means the site changed.
    def form_with(self, button: str, fields: dict[str, str] | None = None) -> Form:
        for form in self.forms:
            if button in form.buttons and (fields or {}).items() <= form.fields.items():
                return form
        raise EfsError(f"eManager's page has no {button!r} button{f' for {fields}' if fields else ''} any more. "
                       "The site changed; check it by hand.")


# Reads a page: who is logged in, its forms and its tables.
def parse(url: str, html: str) -> Page:
    reader = _Reader()
    reader.feed(html)
    user = re.search(r"Logged in as:\s*(\S+)", "".join(reader.text))
    return Page(url, html, user.group(1) if user else "", reader.forms, reader.rows)


# Walks a page's HTML once: forms with the values a browser would send, and table rows of cell texts.
class _Reader(HTMLParser):
    # Starts with no forms, no tables, no text.
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.forms: list[Form] = []
        self.rows: dict[str, list[list[str]]] = {}
        self.text: list[str] = []
        self.in_form = False
        self.select = ""
        # one entry per open table: its id, the row being read, the cell being read
        self.tables: list[dict] = []

    # An opening tag: a form, a table and its rows and cells, an input, a select and its chosen option.
    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        table = self.tables[-1] if self.tables else None
        if tag == "form":
            self.forms.append(Form(attrs.get("action") or ""))
            self.in_form = True
        elif tag == "table":
            self.tables.append({"id": attrs.get("id") or "", "row": None, "cell": None})
        elif tag == "tr" and table:
            table["row"] = []
        elif tag in ("td", "th") and table and table["row"] is not None:
            table["cell"] = []
        elif tag == "input" and self.in_form:
            self._input(attrs)
        elif tag == "select" and self.in_form:
            self.select = attrs.get("name") or ""
        elif tag == "option" and self.select and "selected" in attrs:
            self.forms[-1].fields[self.select] = attrs.get("value") or ""

    # A closing tag: finishes the form, select, cell, row or table it closes.
    def handle_endtag(self, tag):
        table = self.tables[-1] if self.tables else None
        if tag == "form":
            self.in_form = False
        elif tag == "select":
            self.select = ""
        elif tag == "table" and table:
            self.tables.pop()
        elif tag in ("td", "th") and table and table["cell"] is not None and table["row"] is not None:
            table["row"].append(" ".join("".join(table["cell"]).split()))
            table["cell"] = None
        elif tag == "tr" and table and table["row"]:
            self.rows.setdefault(table["id"], []).append(table["row"])
            table["row"] = None

    # Text: kept for the page, and for the cell being read.
    def handle_data(self, data):
        self.text.append(data)
        if self.tables and self.tables[-1]["cell"] is not None:
            self.tables[-1]["cell"].append(data)

    # One input: a button, a ticked choice, or a value the form sends.
    def _input(self, attrs):
        name, kind = attrs.get("name"), (attrs.get("type") or "text").lower()
        if not name:
            return
        form = self.forms[-1]
        if kind in ("submit", "image"):
            form.buttons[name] = attrs.get("value") or ""
        elif kind in ("radio", "checkbox"):
            if "checked" in attrs:
                form.fields[name] = attrs.get("value") or "on"
        elif kind not in ("reset", "button", "file"):
            form.fields[name] = attrs.get("value") or ""

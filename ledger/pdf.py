"""Builds timesheet and invoice PDFs with ReportLab. No Qt in here.

The preview is drawn from these exact bytes, so what you see is what exports.

Page header layout: five slots (top left/centre/right, then info left/right under the rule).
The profile says which slot each element sits in: logo, your details, bill to, details.
"""
from __future__ import annotations

import io
from dataclasses import dataclass
from pathlib import Path
from xml.sax.saxutils import escape

from PIL import Image as PILImage
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4, LETTER, landscape, portrait
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.platypus import (BaseDocTemplate, CondPageBreak, Frame, HRFlowable, Image, KeepTogether, PageBreak,
                                PageTemplate, Paragraph, Spacer, Table, TableStyle)

from . import fonts
from .colors import resolve_accent, text_on
from .model import DocSpec
from .store import FONT_SIZES, MARGINS_MM, Profile, normalise_layout

TEXT = colors.HexColor("#1F2328")
MUTED = colors.HexColor("#5B616B")
RULE = colors.HexColor("#D9DCE1")
ZEBRA = colors.HexColor("#F5F6F8")
ALIGN = {"left": TA_LEFT, "center": TA_CENTER, "right": TA_RIGHT}
CELL_PAD = 5


@dataclass
class Result:
    data: bytes
    pages: int


def _p(text: str) -> str:
    """Plain text -> safe Paragraph markup, keeping line breaks."""
    return "<br/>".join(escape(line) for line in (text or "").split("\n"))


class _Ctx:
    """Fonts, sizes and colours for one build."""

    def __init__(self, profile: Profile, logo_path: Path | None):
        self.profile = profile
        self.body, self.body_bold = fonts.resolve(profile.body_font)
        self.head, self.head_bold = fonts.resolve(profile.heading_font)
        self.size = FONT_SIZES.get(profile.font_size, 10.5)
        accent = resolve_accent(profile.accent, logo_path)
        self.accent = colors.HexColor(accent)
        self.on_accent = colors.HexColor(text_on(accent, profile.header_text))
        size = LETTER if profile.page_size == "letter" else A4
        self.page = landscape(size) if profile.orientation == "landscape" else portrait(size)
        self.margin = MARGINS_MM.get(profile.margins, 19.05) * mm
        self.width = self.page[0] - 2 * self.margin
        s = self.size
        self.st = {
            "title": ParagraphStyle("title", fontName=self.head_bold, fontSize=s * 1.9, leading=s * 2.3, textColor=TEXT),
            "desc": ParagraphStyle("desc", fontName=self.body, fontSize=s, leading=s * 1.4, textColor=TEXT),
            "meta": ParagraphStyle("meta", fontName=self.body, fontSize=s * 0.88, leading=s * 1.25, textColor=MUTED),
            "section": ParagraphStyle("section", fontName=self.head_bold, fontSize=s * 1.25, leading=s * 1.6,
                                      textColor=TEXT),
            "label": ParagraphStyle("label", fontName=self.body_bold, fontSize=s * 0.78, leading=s * 1.2,
                                    textColor=MUTED),
            "block": ParagraphStyle("block", fontName=self.body, fontSize=s * 0.95, leading=s * 1.3, textColor=TEXT),
            "footer": ParagraphStyle("footer", fontName=self.body, fontSize=s * 0.8, leading=s * 1.1,
                                     textColor=MUTED),
        }

    def style(self, base: str, align: str) -> ParagraphStyle:
        return ParagraphStyle(f"{base}-{align}", parent=self.st[base], alignment=ALIGN.get(align, TA_LEFT))

    def cell_style(self, align: str, bold: bool = False, header: bool = False, small: bool = False) -> ParagraphStyle:
        s = self.size * (0.82 if small else 0.95)
        return ParagraphStyle(f"cell-{align}-{bold}-{header}-{small}",
                              fontName=self.body_bold if (bold or header) else self.body,
                              fontSize=s, leading=s * 1.25, alignment=ALIGN.get(align, TA_LEFT),
                              textColor=self.on_accent if header else (MUTED if small else TEXT))


# ---- images --------------------------------------------------------------------------------
def _image_reader(path: Path | None, opacity: float = 1.0) -> ImageReader | None:
    if path is None:
        return None
    try:
        img = PILImage.open(path)
        img.load()
        if opacity < 1.0:
            img = img.convert("RGBA")
            img.putalpha(img.getchannel("A").point(lambda a: int(a * opacity)))
        return ImageReader(img)
    except Exception:      # noqa: BLE001 - a missing or broken image is just left out
        return None


def _logo(ctx: _Ctx, path: Path | None, align: str) -> Image | None:
    reader = _image_reader(path)
    if reader is None:
        return None
    w, h = reader.getSize()
    if not w or not h:
        return None
    height = max(5.0, ctx.profile.logo_height_mm) * mm
    width = height * w / h
    if width > ctx.width * 0.45:
        width = ctx.width * 0.45
        height = width * h / w
    img = Image(str(path), width=width, height=height)
    img.hAlign = {"left": "LEFT", "center": "CENTER", "right": "RIGHT"}[align]
    return img


# ---- header blocks ---------------------------------------------------------------------------------
@dataclass
class HeaderParts:
    bill_label: str = ""                 # "Bill to" / "Prepared for"
    bill_name: str = ""
    bill_text: str = ""
    details: list[tuple[str, str]] | None = None    # label/value rows


def _sender(ctx: _Ctx, align: str) -> Paragraph | None:
    text = ctx.profile.contact.strip()
    if not text:
        return None
    lines = text.split("\n")
    markup = f"<font name='{ctx.body_bold}'>{escape(lines[0])}</font>"
    if len(lines) > 1:
        markup += "<br/>" + _p("\n".join(lines[1:]))
    return Paragraph(markup, ctx.style("block", align))


def _billto(ctx: _Ctx, parts: HeaderParts, align: str) -> list | None:
    if not (parts.bill_name or parts.bill_text):
        return None
    out = [Paragraph(escape(parts.bill_label.upper()), ctx.style("label", align))]
    markup = ""
    if parts.bill_name:
        markup = f"<font name='{ctx.body_bold}'>{escape(parts.bill_name)}</font>"
    if parts.bill_text.strip():
        markup += ("<br/>" if markup else "") + _p(parts.bill_text.strip())
    out.append(Paragraph(markup, ctx.style("block", align)))
    return out


def _details(ctx: _Ctx, parts: HeaderParts, align: str) -> Table | None:
    if not parts.details:
        return None
    lab = ctx.style("block", "right" if align != "left" else "left")
    lab = ParagraphStyle("dl", parent=lab, textColor=MUTED)
    val = ctx.style("block", "right" if align != "left" else "left")
    data = [[Paragraph(escape(k), lab), Paragraph(f"<font name='{ctx.body_bold}'>{escape(v)}</font>", val)]
            for k, v in parts.details]
    w1 = max(stringWidth(k, ctx.body, ctx.size * 0.95) for k, _ in parts.details) + 14
    w2 = max(stringWidth(v, ctx.body_bold, ctx.size * 0.95) for _, v in parts.details) + 14
    t = Table(data, colWidths=[w1, w2], hAlign={"left": "LEFT", "center": "CENTER", "right": "RIGHT"}[align])
    t.setStyle(TableStyle([("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                           ("TOPPADDING", (0, 0), (-1, -1), 1), ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
                           ("RIGHTPADDING", (0, 0), (0, -1), 10)]))
    return t


def _slot_align(slot: str) -> str:
    return "center" if slot.endswith("center") else ("right" if slot.endswith("right") else "left")


def _row(ctx: _Ctx, cells: dict[str, list], slots: list[str]) -> Table | None:
    used = [s for s in slots if cells.get(s)]
    if not used:
        return None
    if any(s.endswith("center") for s in used) and len(used) > 1:
        cols = slots                            # three equal columns
    else:
        cols = used
    widths = [ctx.width / len(cols)] * len(cols)
    data = [[cells.get(s) or "" for s in cols]]
    t = Table(data, colWidths=widths)
    style = [("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0),
             ("RIGHTPADDING", (0, 0), (-1, -1), 0), ("TOPPADDING", (0, 0), (-1, -1), 0),
             ("BOTTOMPADDING", (0, 0), (-1, -1), 0)]
    for i, s in enumerate(cols):
        style.append(("ALIGN", (i, 0), (i, 0), _slot_align(s).upper() if _slot_align(s) != "center" else "CENTER"))
    if len(cols) > 1:
        style.append(("RIGHTPADDING", (0, 0), (-2, 0), 12))
    t.setStyle(TableStyle(style))
    return t


def _header(ctx: _Ctx, parts: HeaderParts, logo_path: Path | None, title: str, subtitle: str = "") -> list:
    layout = normalise_layout(ctx.profile.layout)
    cells: dict[str, list] = {}

    def put(element: str, builder) -> None:
        slot = layout[element]
        block = builder(_slot_align(slot))
        if block:
            blocks = block if isinstance(block, list) else [block]
            if cells.get(slot):
                cells[slot].append(Spacer(1, ctx.size * 0.5))
            cells.setdefault(slot, []).extend(blocks)

    put("logo", lambda a: _logo(ctx, logo_path, a))
    put("sender", lambda a: _sender(ctx, a))
    put("billto", lambda a: _billto(ctx, parts, a))
    put("details", lambda a: _details(ctx, parts, a))

    out: list = []
    top = _row(ctx, cells, ["top-left", "top-center", "top-right"])
    if top is not None:
        out += [top, Spacer(1, ctx.size * 0.9),
                HRFlowable(width="100%", thickness=1.2, color=ctx.accent, spaceBefore=0, spaceAfter=ctx.size * 1.3)]
    out.append(Paragraph(_p(title), ctx.st["title"]))
    if subtitle:
        out += [Spacer(1, ctx.size * 0.15), Paragraph(subtitle, ctx.st["meta"])]
    info = _row(ctx, cells, ["info-left", "info-right"])
    if info is not None:
        out += [Spacer(1, ctx.size * 1.1), info]
    out.append(Spacer(1, ctx.size * 1.4))
    return out


# ---- timesheet tables --------------------------------------------------------------------------------
def _column_widths(ctx: _Ctx, spec: DocSpec) -> list[float]:
    fs = ctx.size * 0.95
    flex_keys = {"step", "checklist"}
    natural = []
    for i, col in enumerate(spec.columns):
        w = stringWidth(col.label, ctx.body_bold, fs)
        for sec in spec.sections:
            for row in sec.rows:
                w = max(w, stringWidth(row[i], ctx.body, fs))
            w = max(w, stringWidth(sec.total, ctx.body_bold, fs))
        natural.append(w + 2 * CELL_PAD + 2)
    fixed_idx = [i for i, c in enumerate(spec.columns) if c.key not in flex_keys]
    flex_idx = [i for i, c in enumerate(spec.columns) if c.key in flex_keys]
    widths = list(natural)
    if not flex_idx:
        total = sum(widths)
        return [w * ctx.width / total for w in widths]
    fixed_total = sum(widths[i] for i in fixed_idx)
    cap = ctx.width * 0.68
    if fixed_total > cap:
        for i in fixed_idx:
            widths[i] *= cap / fixed_total
        fixed_total = cap
    rest = ctx.width - fixed_total
    flex_natural = sum(natural[i] for i in flex_idx)
    for i in flex_idx:
        share = natural[i] / flex_natural if flex_natural else 1 / len(flex_idx)
        widths[i] = rest * (share * 0.5 + 0.5 / len(flex_idx))
    return widths


def _base_table_style(ctx: _Ctx, n_rows: int) -> list:
    style = [
        ("BACKGROUND", (0, 0), (-1, 0), ctx.accent),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), CELL_PAD), ("RIGHTPADDING", (0, 0), (-1, -1), CELL_PAD),
        ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LINEBELOW", (0, 1), (-1, -1), 0.5, RULE),
    ]
    for i in range(1, n_rows):
        if i % 2 == 0:
            style.append(("BACKGROUND", (0, i), (-1, i), ZEBRA))
    return style


def _table(ctx: _Ctx, spec: DocSpec, rows: list[list[str]], total_label: str, total: str,
           widths: list[float]) -> Table:
    cols = spec.columns
    data = [[Paragraph(_p(c.label), ctx.cell_style(c.align, header=True)) for c in cols]]
    for r in rows:
        data.append([Paragraph(_p(v), ctx.cell_style(c.align)) for c, v in zip(cols, r)])
    empty = not rows
    if empty:
        data.append([Paragraph("No steps", ctx.cell_style("left"))] + [""] * (len(cols) - 1))
    style = _base_table_style(ctx, len(data))
    if empty and len(cols) > 1:
        style.append(("SPAN", (0, 1), (-1, 1)))
    dcol = next((i for i, c in enumerate(cols) if c.key == "duration"), None)
    if dcol is not None:
        label_col = None if len(cols) == 1 else (0 if dcol != 0 else 1)
        row = [""] * len(cols)
        row[dcol] = Paragraph(escape(total), ctx.cell_style("right", bold=True))
        last = len(data)
        if label_col is not None:
            row[label_col] = Paragraph(escape(total_label), ctx.cell_style("left", bold=True))
            span_end = dcol - 1 if label_col < dcol else len(cols) - 1
            if span_end > label_col:
                style.append(("SPAN", (label_col, last), (span_end, last)))
        data.append(row)
        style += [("LINEABOVE", (0, last), (-1, last), 1.1, ctx.accent),
                  ("LINEBELOW", (0, last), (-1, last), 0, colors.white),
                  ("BACKGROUND", (0, last), (-1, last), colors.white)]
    t = Table(data, colWidths=widths, repeatRows=1, hAlign="LEFT")
    t.setStyle(TableStyle(style))
    return t


def _grand_total(ctx: _Ctx, label: str, value: str, value_width: float) -> Table:
    s = ctx.size * 1.05
    st = ParagraphStyle("gt", fontName=ctx.head_bold, fontSize=s, leading=s * 1.3, textColor=TEXT, alignment=TA_RIGHT)
    vw = max(value_width, stringWidth(value, ctx.head_bold, s) + 2 * CELL_PAD + 4)
    t = Table([[Paragraph(escape(label), st), Paragraph(escape(value), st)]], colWidths=[ctx.width - vw, vw],
              hAlign="LEFT")
    t.setStyle(TableStyle([("LINEABOVE", (0, 0), (-1, 0), 1.6, ctx.accent),
                           ("LEFTPADDING", (0, 0), (-1, -1), CELL_PAD), ("RIGHTPADDING", (0, 0), (-1, -1), CELL_PAD),
                           ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6)]))
    return t


def _category_summary(ctx: _Ctx, spec: DocSpec) -> list:
    if not spec.categories:
        return []
    fs = ctx.size * 0.95
    w2 = max([stringWidth(t, ctx.body_bold, fs) for _, t in spec.categories] +
             [stringWidth(spec.category_total, ctx.body_bold, fs), stringWidth("Time", ctx.body_bold, fs)]) + 2 * CELL_PAD + 6
    w1 = max(ctx.width * 0.5 - w2, max(stringWidth(c, ctx.body, fs) for c, _ in spec.categories) + 2 * CELL_PAD + 6)
    data = [[Paragraph("Category", ctx.cell_style("left", header=True)),
             Paragraph("Time", ctx.cell_style("right", header=True))]]
    data += [[Paragraph(escape(c), ctx.cell_style("left")), Paragraph(escape(t), ctx.cell_style("right"))]
             for c, t in spec.categories]
    last = len(data)
    data.append([Paragraph("Total", ctx.cell_style("left", bold=True)),
                 Paragraph(escape(spec.category_total), ctx.cell_style("right", bold=True))])
    style = _base_table_style(ctx, last)
    style += [("LINEABOVE", (0, last), (-1, last), 1.1, ctx.accent), ("LINEBELOW", (0, last), (-1, last), 0, colors.white)]
    t = Table(data, colWidths=[w1, w2], hAlign="LEFT")
    t.setStyle(TableStyle(style))
    head = [Paragraph("Time by category", ctx.st["section"]), Spacer(1, ctx.size * 0.5)]
    return [CondPageBreak(ctx.size * 8), KeepTogether(head + [t])]


def timesheet_body(ctx: _Ctx, spec: DocSpec) -> list:
    """The tables of a timesheet (no header)."""
    story: list = []
    widths = _column_widths(ctx, spec)
    for sec in spec.sections:
        if sec.heading:
            head = [Paragraph(_p(sec.heading), ctx.st["section"])]
            if sec.subheading:
                head.append(Paragraph(escape(sec.subheading), ctx.st["meta"]))
            head.append(Spacer(1, ctx.size * 0.5))
            table = _table(ctx, spec, sec.rows, sec.total_label, sec.total, widths)
            story.append(CondPageBreak(ctx.size * 9))
            if len(sec.rows) < 8:
                story.append(KeepTogether(head + [table]))
            else:
                story += [KeepTogether(head), table]
            story.append(Spacer(1, ctx.size * 1.6))
        else:
            story.append(_table(ctx, spec, sec.rows, sec.total_label, sec.total, widths))
            story.append(Spacer(1, ctx.size * 1.6))
    if spec.grand_total is not None:
        dcol = next((i for i, c in enumerate(spec.columns) if c.key == "duration"), None)
        if dcol is not None:
            story.append(_grand_total(ctx, "Grand total", spec.grand_total, widths[dcol]))
            story.append(Spacer(1, ctx.size * 1.6))
    story += _category_summary(ctx, spec)
    return story


# ---- invoice -----------------------------------------------------------------------------------------
def _invoice_items(ctx: _Ctx, spec) -> Table:
    from .invoicing import line_cells
    fs = ctx.size * 0.95
    rows = [[Paragraph("Description", ctx.cell_style("left", header=True)),
             Paragraph("Qty", ctx.cell_style("right", header=True)),
             Paragraph("Rate", ctx.cell_style("right", header=True)),
             Paragraph("Amount", ctx.cell_style("right", header=True))]]
    cells = []
    for ln in spec.totals.lines:
        qty, rate, amount = line_cells(ln, spec.currency)
        cells.append((ln, qty, rate, amount))
    nat = [0.0, stringWidth("Qty", ctx.body_bold, fs), stringWidth("Rate", ctx.body_bold, fs),
           stringWidth("Amount", ctx.body_bold, fs)]
    for _, q, r, a in cells:
        nat[1] = max(nat[1], stringWidth(q, ctx.body, fs))
        nat[2] = max(nat[2], stringWidth(r, ctx.body, fs))
        nat[3] = max(nat[3], stringWidth(a, ctx.body, fs))
    fixed = [w + 2 * CELL_PAD + 8 for w in nat[1:]]
    widths = [ctx.width - sum(fixed)] + fixed
    for ln, q, r, a in cells:
        desc = [Paragraph(_p(ln.description), ctx.cell_style("left"))]
        if ln.detail:
            desc.append(Paragraph(_p(ln.detail), ctx.cell_style("left", small=True)))
        warn = ln.unpriced
        rows.append([desc, Paragraph(escape(q), ctx.cell_style("right")),
                     Paragraph(f"<font color='#B0412A'>{escape(r)}</font>" if warn else escape(r),
                               ctx.cell_style("right")),
                     Paragraph(escape(a), ctx.cell_style("right"))])
    if not cells:
        rows.append([Paragraph("No items yet", ctx.cell_style("left", small=True)), "", "", ""])
    t = Table(rows, colWidths=widths, repeatRows=1, hAlign="LEFT")
    t.setStyle(TableStyle(_base_table_style(ctx, len(rows))))
    return t


def _invoice_totals(ctx: _Ctx, spec) -> Table:
    from .money import fmt_money, fmt_number
    t = spec.totals
    rows = [("Subtotal", fmt_money(t.subtotal, spec.currency))]
    if t.discount:
        rows.append((t.discount_label, "-" + fmt_money(t.discount, spec.currency)))
    for tax in t.taxes:
        rows.append((f"{tax.name} ({fmt_number(tax.rate, 3)}%)", fmt_money(tax.amount, spec.currency)))
    total_label = f"Total ({spec.currency})"
    if spec.status == "paid":
        total_label = f"Total paid ({spec.currency})"
    s = ctx.size
    lab = ParagraphStyle("tl", fontName=ctx.body, fontSize=s * 0.95, leading=s * 1.3, textColor=MUTED, alignment=TA_RIGHT)
    val = ParagraphStyle("tv", fontName=ctx.body, fontSize=s * 0.95, leading=s * 1.3, textColor=TEXT, alignment=TA_RIGHT)
    big = ParagraphStyle("tb", fontName=ctx.head_bold, fontSize=s * 1.2, leading=s * 1.5, textColor=TEXT,
                         alignment=TA_RIGHT)
    data = [[Paragraph(escape(a), lab), Paragraph(escape(b), val)] for a, b in rows]
    data.append([Paragraph(escape(total_label), big), Paragraph(escape(fmt_money(t.total, spec.currency)), big)])
    w2 = max(stringWidth(fmt_money(t.total, spec.currency), ctx.head_bold, s * 1.2),
             max(stringWidth(b, ctx.body, s * 0.95) for _, b in rows)) + 2 * CELL_PAD + 6
    w1 = max(ctx.width * 0.45 - w2, stringWidth(total_label, ctx.head_bold, s * 1.2) + 2 * CELL_PAD + 4)
    table = Table(data, colWidths=[w1, w2], hAlign="RIGHT")
    last = len(data) - 1
    table.setStyle(TableStyle([("LEFTPADDING", (0, 0), (-1, -1), CELL_PAD), ("RIGHTPADDING", (0, 0), (-1, -1), CELL_PAD),
                               ("TOPPADDING", (0, 0), (-1, -1), 2), ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
                               ("LINEABOVE", (0, last), (-1, last), 1.6, ctx.accent),
                               ("TOPPADDING", (0, last), (-1, last), 6)]))
    return table


def invoice_story(ctx: _Ctx, spec, logo_path: Path | None) -> list:
    details = [("Invoice no.", spec.number or "—"), ("Date", spec.issue)]
    if spec.status == "paid":
        details.append(("Status", "Paid"))
    elif spec.due:
        details.append(("Due", spec.due))
    details.append(("Terms", spec.terms))
    parts = HeaderParts("Bill to", spec.client_name, spec.bill_to, details)
    story = _header(ctx, parts, logo_path, spec.title)
    story.append(_invoice_items(ctx, spec))
    story.append(Spacer(1, ctx.size * 0.8))
    story.append(_invoice_totals(ctx, spec))
    extra: list = []
    for heading, text in (("Notes", spec.notes), ("Payment", spec.payment)):
        if text and text.strip():
            extra += [Spacer(1, ctx.size * 1.2), Paragraph(heading.upper(), ctx.st["label"]),
                      Paragraph(_p(text.strip()), ctx.st["desc"])]
    if spec.tax_number.strip():
        extra += [Spacer(1, ctx.size * 1.0), Paragraph(_p(spec.tax_number.strip()), ctx.st["meta"])]
    if extra:
        story.append(KeepTogether(extra))
    if spec.attachment is not None:
        story.append(PageBreak())
        att = spec.attachment
        sub = f"Attachment to invoice {escape(spec.number)}" if spec.number else "Attachment to invoice"
        if att.date_range:
            sub += f" &nbsp;·&nbsp; {escape(att.date_range)}"
        story += [Paragraph("Timesheet", ctx.st["title"]), Spacer(1, ctx.size * 0.15),
                  Paragraph(sub, ctx.st["meta"]), Spacer(1, ctx.size * 1.4)]
        story += timesheet_body(ctx, att)
    return story


def timesheet_story(ctx: _Ctx, spec: DocSpec, logo_path: Path | None, prepared_for: tuple[str, str] | None) -> list:
    details = []
    if ctx.profile.show_date_range and spec.date_range:
        details.append(("Period", spec.date_range))
    if ctx.profile.show_generated:
        details.append(("Generated", spec.generated))
    name, text = prepared_for or ("", "")
    parts = HeaderParts("Prepared for", name, text, details or None)
    story = _header(ctx, parts, logo_path, spec.title or "Timesheet")
    if spec.description.strip():
        story.insert(len(story) - 1, Spacer(1, ctx.size * 0.6))
        story.insert(len(story) - 1, Paragraph(_p(spec.description.strip()), ctx.st["desc"]))
    return story + timesheet_body(ctx, spec)


# ---- pages ---------------------------------------------------------------------------------
def _page_label(style: str, n: int, total: int) -> str:
    if style == "slash":
        return f"{n} / {total}"
    if style == "plain":
        return str(n)
    return f"Page {n} of {total}"


def _build(ctx: _Ctx, make_story, title: str, author: str, watermark_path: Path | None,
           footer_label: str = "", stamp: str = "") -> Result:
    profile = ctx.profile
    pn = profile.page_numbers
    pn_size = ctx.size * 0.8
    pn_h = pn_size * 1.6
    footer_para = None
    footer_h = 0.0
    if profile.footer.strip():
        footer_para = Paragraph(_p(profile.footer.strip()), ctx.st["footer"])
        _, footer_h = footer_para.wrap(ctx.width, ctx.page[1])
    bottom = ctx.margin
    if footer_para is not None:
        bottom += footer_h + ctx.size * 0.9
    if pn.startswith("footer") or footer_label:
        bottom += pn_h
    top = ctx.margin + (pn_h if pn == "header-right" else 0)
    wm_reader = _image_reader(watermark_path, max(0.02, min(1.0, profile.watermark_opacity / 100)))

    def make(total_pages: int) -> tuple[bytes, int]:
        buf = io.BytesIO()
        count = {"n": 0}

        def on_page(c, doc):
            count["n"] = doc.page
            c.saveState()
            if wm_reader is not None:
                w, h = wm_reader.getSize()
                width = ctx.page[0] * max(10, min(100, profile.watermark_size)) / 100
                height = width * h / w if w else 0
                c.drawImage(wm_reader, (ctx.page[0] - width) / 2, (ctx.page[1] - height) / 2, width, height,
                            mask="auto")
            y = ctx.margin + (pn_h if (pn.startswith("footer") or footer_label) else 0)
            if footer_para is not None:
                footer_para.wrap(ctx.width, ctx.page[1])
                footer_para.drawOn(c, ctx.margin, y)
                c.setStrokeColor(RULE)
                c.setLineWidth(0.6)
                c.line(ctx.margin, y + footer_h + ctx.size * 0.45, ctx.page[0] - ctx.margin,
                       y + footer_h + ctx.size * 0.45)
            c.setFont(ctx.body, pn_size)
            c.setFillColor(MUTED)
            yy = ctx.margin + pn_size * 0.3
            if footer_label:
                if pn == "footer-left":
                    c.drawRightString(ctx.page[0] - ctx.margin, yy, footer_label)
                else:
                    c.drawString(ctx.margin, yy, footer_label)
            if pn != "off" and (profile.page_number_first or doc.page > 1):
                label = _page_label(profile.page_number_style, doc.page, total_pages or doc.page)
                if pn == "header-right":
                    c.drawRightString(ctx.page[0] - ctx.margin, ctx.page[1] - ctx.margin - pn_size, label)
                elif pn == "footer-left":
                    c.drawString(ctx.margin, yy, label)
                elif pn == "footer-center":
                    c.drawCentredString(ctx.page[0] / 2, yy, label)
                else:
                    c.drawRightString(ctx.page[0] - ctx.margin, yy, label)
            c.restoreState()

        doc = BaseDocTemplate(buf, pagesize=ctx.page, leftMargin=ctx.margin, rightMargin=ctx.margin,
                              topMargin=top, bottomMargin=bottom, title=title, author=author,
                              creator="Docket Ledger", subject=title)
        frame = Frame(ctx.margin, bottom, ctx.width, ctx.page[1] - top - bottom, leftPadding=0, rightPadding=0,
                      topPadding=0, bottomPadding=0, id="body")
        def on_page_end(c, doc):
            if stamp:                     # drawn over the content so tables can't hide it
                c.saveState()
                c.setFillColor(colors.Color(0.75, 0.2, 0.15, alpha=0.13))
                c.setFont(ctx.head_bold, 90)
                c.translate(ctx.page[0] / 2, ctx.page[1] / 2)
                c.rotate(35)
                c.drawCentredString(0, -30, stamp)
                c.restoreState()

        doc.addPageTemplates([PageTemplate(id="page", frames=[frame], onPage=on_page, onPageEnd=on_page_end)])
        doc.build(make_story())
        return buf.getvalue(), count["n"]

    data, pages = make(0)
    if pn != "off" and profile.page_number_style != "plain":
        data, pages = make(pages)
    return Result(data, pages)


def build_timesheet_pdf(spec: DocSpec, profile: Profile, logo_path: Path | None = None,
                        watermark_path: Path | None = None, author: str = "",
                        prepared_for: tuple[str, str] | None = None) -> Result:
    ctx = _Ctx(profile, logo_path)
    return _build(ctx, lambda: timesheet_story(ctx, spec, logo_path, prepared_for), spec.title or "Timesheet",
                  author, watermark_path)


def build_invoice_pdf(spec, profile: Profile, logo_path: Path | None = None, watermark_path: Path | None = None,
                      author: str = "", stamp: str = "") -> Result:
    ctx = _Ctx(profile, logo_path)
    label = f"Invoice {spec.number}" if spec.number else ""
    return _build(ctx, lambda: invoice_story(ctx, spec, logo_path), f"{spec.title} {spec.number}".strip(), author,
                  watermark_path, footer_label=label, stamp=stamp)

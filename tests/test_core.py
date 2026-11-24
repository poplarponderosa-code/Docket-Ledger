"""Tests for everything that isn't the window. Run: python -m pytest tests"""
from __future__ import annotations

import datetime as dt
import json
import shutil
from decimal import Decimal
from pathlib import Path

import pypdfium2 as pdfium
import pytest

from ledger import colors, docket_link, invoicing as I, logs, model, money, pdf, store, timefmt

SAMPLES = Path(__file__).parent / "samples"
MAP = "Map Making 2026-11-23 2223"


def text_of(data: bytes) -> str:
    doc = pdfium.PdfDocument(data)
    return "\n".join(doc[i].get_textpage().get_text_range() for i in range(len(doc)))


def entries(keys=None):
    found = {lg.key: lg for lg in logs.scan(SAMPLES)}
    keys = keys or list(found)
    return [(found[k], model.LogEdits.from_log(found[k])) for k in keys]


# ---- reading Docket 1.3 logs --------------------------------------------------------------------------
def test_reads_docket_13_log():
    lg = logs.log_for_path(SAMPLES / f"{MAP}.csv")
    assert lg.title == "Map Making" and lg.client == "Acme"
    assert lg.description == "Description of making map time record."
    assert len(lg.rows) == 16                       # the Total row is skipped
    assert lg.total_seconds == 196                  # 3:16, from the Duration column
    imp = lg.rows[1]
    assert imp.step == "Import heightmap" and imp.seconds == 5   # paused: Start->End is 61 s, Duration says 0:05
    assert lg.rows[4].limit == "0:10"
    assert lg.rows[-1].category == ""
    assert lg.categories() == ["Setup", "Terrain", "Simulation", "Networks", "Detailing", ""]


def test_txt_only_skips_by_category_section(tmp_path):
    shutil.copy(SAMPLES / f"{MAP}.txt", tmp_path)
    (lg,) = logs.scan(tmp_path)
    assert len(lg.rows) == 16 and lg.total_seconds == 196
    assert lg.client == "Acme" and lg.rows[0].category == "Setup"


def test_description_continues_on_indented_lines(tmp_path):
    (tmp_path / "Job 2026-11-23 1200.txt").write_text(
        "# Docket time log\nChecklist: Job\nDescription: First line\n  second line\nStarted: 2026-11-23 11:00:00\n"
        "Finished: 2026-11-23 12:00:00\n\nStep | Start | End | Duration | Limit\n"
        "A | 2026-11-23 11:00:00 | 2026-11-23 12:00:00 | 1:00:00 | -\nTotal | | | 1:00:00 | -\n", encoding="utf-8")
    (lg,) = logs.scan(tmp_path)
    assert lg.description == "First line\nsecond line" and lg.total_seconds == 3600


def test_older_logs_and_non_docket_files(tmp_path):
    shutil.copy(SAMPLES / "Website_Refresh_2026-11-20_1612.csv", tmp_path)
    (tmp_path / "notes.txt").write_text("hello", encoding="utf-8")
    (tmp_path / "data.csv").write_text("a,b\n1,2\n", encoding="utf-8")
    (lg,) = logs.scan(tmp_path)
    assert lg.title == "Website Refresh" and lg.client == "" and len(lg.rows) == 4


def test_scan_sorted_newest_first():
    assert [lg.title for lg in logs.scan(SAMPLES)] == ["Map Making", "Quarterly Report", "Website Refresh"]


# ---- timesheets --------------------------------------------------------------------------------------
def test_timesheet_with_categories():
    spec = model.build_spec(entries([MAP]), "T", "", model.TableOptions())
    assert [c.key for c in spec.columns] == ["step", "category", "start", "end", "duration"]
    assert spec.sections[0].total == "00:03:16"
    assert spec.categories[0] == ("Setup", "00:00:45")
    assert spec.categories[-1] == ("General", "00:00:07")
    assert spec.category_total == "00:03:16"


def test_category_column_hidden_without_categories():
    spec = model.build_spec(entries(["Quarterly_Report_2026-11-21_1130"]), "T", "", model.TableOptions())
    assert "category" not in [c.key for c in spec.columns] and spec.categories == []


def test_rounding_per_category_matches_summary():
    e = entries([MAP])
    for r in e[0][1].rows:
        r.override = r.seconds * 60           # make it minutes-scale
    opts = model.TableOptions(rounding="nearest15")
    spec = model.build_spec(e, "T", "", opts)
    assert spec.sections[0].total == spec.category_total
    assert spec.billed_seconds % 900 == 0


def test_edits_keep_docket_duration_until_times_change():
    e = entries([MAP])
    row = e[0][1].rows[1]
    assert row.seconds == 5
    row.end = row.end + dt.timedelta(seconds=30)
    assert row.seconds == 91                  # now worked out from Start and End
    row.override = 600
    assert row.seconds == 600


def test_columns_normalise_adds_category_after_step():
    old = [{"key": "step", "label": "Task", "visible": True}, {"key": "duration", "label": "Time", "visible": True}]
    cols = model.normalise_columns(old)
    keys = [c["key"] for c in cols]
    assert keys.index("category") == keys.index("step") + 1
    assert next(c for c in cols if c["key"] == "category")["visible"]


# ---- money and invoices ---------------------------------------------------------------------------------
def test_money_formatting():
    assert money.fmt_money(Decimal("1240.5"), "CAD") == "$1,240.50"
    assert money.fmt_money(Decimal("1240.5"), "EUR", code=True) == "€1,240.50 EUR"
    assert money.fmt_money(Decimal("1240.5"), "JPY") == "¥1,241"
    assert money.dec("$1,200.50") == Decimal("1200.50")
    assert money.dec("abc", None) is None


def test_invoice_totals_with_discount_and_taxes():
    lines = [money.Line("hours", "Design", qty=Decimal("2.5"), price=Decimal("80")),
             money.Line("fixed", "Setup", price=Decimal("150")),
             money.Line("qty", "Prints", qty=Decimal("3"), unit="prints", price=Decimal("12.50"))]
    t = money.compute(lines, "CAD", "percent", "10", [("GST", Decimal("5")), ("PST", Decimal("7"))])
    assert t.subtotal == Decimal("387.50")
    assert t.discount == Decimal("38.75")
    assert [x.amount for x in t.taxes] == [Decimal("17.44"), Decimal("24.41")]
    assert t.total == Decimal("387.50") - Decimal("38.75") + Decimal("17.44") + Decimal("24.41")


def test_invoice_lines_from_log_with_rates_and_unpriced():
    e = entries([MAP])
    for r in e[0][1].rows:
        r.override = r.seconds * 60
    inv = store.Invoice(rounding="nearest6", category_rates={"": "40"})
    client = store.Client(label="Acme", rates={"terrain": "90", "Setup": "60"})
    times = I.category_times(e, [], inv)
    assert [t.label for t in times] == ["Setup", "Terrain", "Simulation", "Networks", "Detailing", "General"]
    lines = I.log_lines(times, inv, client)
    by = {ln.description: ln for ln in lines}
    assert by["Terrain"].price == Decimal("90")          # matched case-insensitively
    assert by["General"].price == Decimal("40")          # typed on the invoice
    assert by["Networks"].unpriced and by["Networks"].amount == 0
    # hours on the invoice add up to the rounded time on the attached timesheet
    opts = model.TableOptions(rounding="nearest6", round_grand_once=True)
    att = model.build_spec(e, "T", "", opts)
    assert sum(ln.qty for ln in lines) == money.hours_from_seconds(att.billed_seconds)


def test_missing_log_uses_saved_totals():
    e = entries([MAP])
    inv = store.Invoice()
    ref = I.ref_for(e[0][0], e[0][1], I.rounding_options(inv))
    times = I.category_times([], [ref], inv)
    assert sum(t.raw for t in times) == 196


def test_invoice_pdf_contents_and_attachment():
    e = entries([MAP])
    for r in e[0][1].rows:
        r.override = r.seconds * 60
    prof = store.Profile(contact="Sample Studio\nhello@example.com", payment="e-Transfer please",
                         tax_number="GST no. 000", footer="Thanks!")
    inv = store.Invoice(issue_date="2026-11-23", due_date="2026-12-23", rounding="nearest6",
                        lines=[{"kind": "fixed", "description": "Preview images", "price": "150"}],
                        taxes=[{"id": "g", "name": "GST", "rate": "5", "on": True}])
    client = store.Client(label="Acme", name="Acme Co.", bill_to="1 Main St", default_rate="60")
    lines = I.log_lines(I.category_times(e, [], inv), inv, client) + I.manual_lines(inv)
    att = model.build_spec(e, "Map Making", "", model.TableOptions(rounding="nearest6", round_grand_once=True))
    spec = I.build_invoice_spec(inv, client, prof, lines, "2026-11-23-01", att)
    res = pdf.build_invoice_pdf(spec, prof)
    text = text_of(res.data)
    for s in ("Invoice", "2026-11-23-01", "Acme Co.", "1 Main St", "Preview images", "GST (5%)", "Total (CAD)",
              "e-Transfer please", "GST no. 000", "Timesheet", "Attachment to invoice 2026-11-23-01",
              "Time by category", "Invoice 2026-11-23-01", "Thanks!"):
        assert s in text, s
    assert res.pages >= 2


@pytest.mark.parametrize("preset", list(store.PRESETS))
def test_layout_presets_build(preset):
    spec = model.build_spec(entries([MAP]), "T", "", model.TableOptions())
    prof = store.Profile(contact="Me", layout=store.PRESETS[preset][1])
    res = pdf.build_timesheet_pdf(spec, prof, prepared_for=("Acme Co.", "1 Main St"))
    text = text_of(res.data)
    assert "PREPARED FOR" in text and "Acme Co." in text and "Period" in text


def test_sample_stamp_and_email_text():
    prof = store.Profile(contact="Sample Studio", payment="Pay by e-Transfer")
    inv = store.Invoice(issue_date="2026-11-23", due_date="2026-12-23",
                        lines=[{"kind": "fixed", "description": "Work", "price": "100"}])
    spec = I.build_invoice_spec(inv, store.Client(name="Acme"), prof, I.manual_lines(inv), "SAMPLE-01")
    assert "SAMPLE" in text_of(pdf.build_invoice_pdf(spec, prof, stamp="SAMPLE").data)
    mail = I.email_text(spec, prof.contact)
    assert "Subject: Invoice SAMPLE-01 from Sample Studio" in mail and "$100.00 CAD" in mail and "Dec 23, 2026" in mail


def test_import_hours_csv(tmp_path):
    f = tmp_path / "export.csv"
    f.write_text("Date,Task,Duration,Tag\n2026-11-20,Logo,1:30,Design\n2026-11-21,Calls,0.5,\n", encoding="utf-8")
    lines = I.import_hours_csv(f)
    assert [(d["description"], d["qty"], d["category"]) for d in lines] == [("Logo", "1.50", "Design"),
                                                                             ("Calls", "0.50", "")]


# ---- numbering, storage, sharing -------------------------------------------------------------------------
def test_invoice_numbers():
    s = store.Settings()
    day = dt.date(2026, 11, 23)
    n, text = s.next_number(day, set())
    assert text == "2026-11-23-01"
    s.commit_number(day, n)
    assert s.next_number(day, set())[1] == "2026-11-23-02"
    assert s.next_number(dt.date(2026, 11, 24), set())[1] == "2026-11-24-01"   # restarts daily
    assert s.next_number(day, {"2026-11-23-02"})[1] == "2026-11-23-03"         # never reuses
    s.number_format = "INV-{NNNN}"
    s.set_next(day, 120)
    assert s.next_number(dt.date(2027, 1, 1), set())[1] == "INV-0120"          # never resets
    assert store.reset_period("{YYYY}-{NNN}") == "year"
    assert not store.number_format_ok("INV-")


def test_data_roundtrip_and_invoiced_logs(tmp_path):
    d = store.Data(tmp_path)
    c = store.Client(label="Acme", aliases=["ACME corp"], rates={"Terrain": "90"})
    d.upsert_client(c)
    inv = store.Invoice(client_id=c.id, number="2026-11-23-01", status="sent",
                        log_refs=[{"key": MAP, "categories": {}}])
    d.invoices.save(inv)
    draft = store.Invoice(log_refs=[{"key": "other"}])
    d.invoices.save(draft)
    d2 = store.Data(tmp_path)
    assert d2.client_for_label("acme").id == c.id and d2.client_for_label("acme CORP").id == c.id
    assert d2.client(c.id).rate_for("TERRAIN") == "90"
    assert d2.invoices.invoiced_logs() == {MAP: ["2026-11-23-01"]}            # drafts don't count
    assert d2.invoices.invoiced_logs(exclude_id=inv.id) == {}
    assert d2.category_names() == ["Terrain"]


def test_profile_export_import(tmp_path):
    from PIL import Image
    a = store.Data(tmp_path / "a")
    logo = tmp_path / "logo.png"
    Image.new("RGBA", (40, 20), (200, 30, 30, 255)).save(logo)
    p = a.profile()
    p.contact = "Someone"
    p.logo = a.import_image(logo)
    p.taxes = [{"id": "x", "name": "GST", "rate": "5"}]
    a.replace_profile(p.name, p)
    a.export_profile(p.name, tmp_path / "shared.json")
    b = store.Data(tmp_path / "b")
    q = b.import_profile(tmp_path / "shared.json")
    assert q.contact == "Someone" and b.image_path(q.logo) is not None and q.taxes[0]["name"] == "GST"


def test_backup(tmp_path):
    d = store.Data(tmp_path / "data")
    d.invoices.save(store.Invoice(number="1"))
    out = d.backup(tmp_path / "bk")
    import zipfile
    assert any(n.startswith("invoices/") for n in zipfile.ZipFile(out).namelist())


def test_shared_json(tmp_path, monkeypatch):
    monkeypatch.setenv("DOCKET_DATA", str(tmp_path))
    assert not docket_link.write_categories(["A"])          # Docket not installed: nothing written
    (tmp_path / "shared.json").write_text(json.dumps({"timelog_dir": str(SAMPLES), "docket_version": "1.3.0"}),
                                          encoding="utf-8")
    assert docket_link.logs_dir() == SAMPLES
    assert docket_link.write_categories(["terrain", "Setup", " "])
    data = json.loads((tmp_path / "shared.json").read_text(encoding="utf-8"))
    assert data["categories"] == ["Setup", "terrain"] and data["docket_version"] == "1.3.0"


# ---- colours and formats ----------------------------------------------------------------------------------
def test_logo_colours_and_contrast(tmp_path):
    from PIL import Image, ImageDraw
    img = Image.new("RGBA", (100, 100), (255, 255, 255, 0))
    d = ImageDraw.Draw(img)
    d.rectangle((0, 0, 70, 100), fill=(46, 125, 96, 255))
    d.rectangle((70, 0, 100, 100), fill=(240, 200, 60, 255))
    p = tmp_path / "logo.png"
    img.save(p)
    found = colors.logo_colors(p)
    assert len(found) == 2 and found[0].startswith("#2")
    assert colors.text_on("#F2C94C") == colors.DARK_TEXT
    assert colors.text_on("#3F4A5A") == colors.LIGHT_TEXT
    assert colors.resolve_accent("", None) == colors.DEFAULT_ACCENT


def test_time_formats():
    assert timefmt.fmt_duration(6432, "hms") == "01:47:12"
    assert timefmt.fmt_duration(6432, "decimal") == "1.79"
    assert timefmt.round_seconds(8 * 60, "nearest15") == 900
    assert timefmt.parse_duration("2h 15m") == 8100

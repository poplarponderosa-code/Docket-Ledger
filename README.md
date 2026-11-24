# Docket Ledger

Timesheets and invoices as clean PDFs, from [Docket](https://github.com/poplarponderosa-code/Docket)
time logs or on their own. A companion app for Docket, for Windows 10 and 11.

- **Timesheets** from Docket time logs: an editable table, categories, rounding, several logs combined,
  and a "Time by category" summary.
- **Invoices** from time logs (one line per category, at each client's rates) or from scratch: hourly,
  fixed-price and quantity items, discounts, tax lines, any currency, and invoice numbers in your own format.
  The timesheet can ride along as an attachment in the same PDF.
- **History** of every invoice (Draft, Sent, Paid, overdue), with a warning before billing a log twice.
- **Your business profile** (details, logo, header colour taken from the logo, layout you arrange by dragging,
  footer, page setup, taxes) and a **client list** (label, bill-to, currency, terms, rates per category).
- **Light and dark**, following Windows by default.
- A live preview drawn from the exact PDF you'll export.

## Your data stays on your PC

Everything is saved in `%APPDATA%\Docket Ledger`. There's no account and nothing is uploaded. Client details
(contacts, bill-to addresses, rates, invoices) never leave Ledger: Docket and other apps only ever see a short
client label such as "Acme". The only time Ledger goes online is the update check, which you can turn off.

The one thing Ledger writes outside its own folder is the list of category names that have rates (no client
names, no rates), added to Docket's `%APPDATA%\Docket\shared.json` so Docket can suggest them.

## Working with Docket

- Ledger finds Docket's time logs folder in `%APPDATA%\Docket\shared.json` (or choose one in Settings).
- Docket starts it with `--folder "<time logs folder>"` and `--open "<log .csv or .txt>"`. If Ledger is already
  open, the log opens in that window.
- The installer registers `DocketLedger.exe` under Windows App Paths so Docket can tell it's installed.

## Running and building

```
run_from_source.bat              run from the Python files
build.bat                        dist\Docket Ledger\DocketLedger.exe
build_installer.bat              installer_output\DocketLedger-Setup-<version>.exe (needs Inno Setup 6)
python -m pytest tests           tests (pip install pytest first)
```

Releases go to `github.com/poplarponderosa-code/Docket-Ledger` with the setup `.exe` attached (its name must
contain "setup"). Ledger's update check and Docket's Install button both use the latest full release;
pre-releases are ignored, so test builds can go out as pre-releases.

## Made with

PySide6 (Qt), ReportLab, pypdfium2 and Pillow. See THIRD-PARTY-NOTICES.txt.

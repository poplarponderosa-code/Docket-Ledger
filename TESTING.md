# Click-through checklist (Docket Ledger 1.0.0)

The PDF, invoice maths, log reading and storage are covered by `tests/`. The window couldn't be run where it
was built, so these checks are the first time the interface runs for real. Note anything that looks off.

## First run
- [ ] Setup opens. With Docket installed, it says "Docket found" and pre-ticks the two Docket boxes.
- [ ] Business page: pick a logo; the header colour swatches change to the logo's colours.
- [ ] Invoicing page: the "First invoice" number updates when you change the format or tick "Continuing from".
- [ ] Data page: choose a backup folder. Ready page: "Try a sample invoice" opens a sample stamped SAMPLE.

## Timesheets
- [ ] The Map Making log shows Category and the "Time by category" table; the total is 0:03:16.
- [ ] Edit a cell, hide a row, add a row; the preview follows. "Reset to original" undoes it.
- [ ] Tick two logs: sections with subtotals and a grand total. Columns… reorders and renames.
- [ ] "Prepared for" picks the client automatically when the log's client label matches one.

## Clients and invoices
- [ ] Invoice mode, tick a log with an unknown client label: "Which client?" offers use / new / skip.
- [ ] New client: label, bill-to, rates (categories from the logs are listed), taxes.
- [ ] Time from Docket shows one line per category; a category without a rate is highlighted; typing a rate
      works and "Save these rates to the client" stores it.
- [ ] Items: add Hours, Quantity and Fixed price rows; Saved items ▾; Import hours… with a CSV.
- [ ] Discount and tax checkboxes change the totals line and the preview.
- [ ] Export: the number is given (2026-…-01), status becomes Sent, the PDF opens/folder opens as ticked,
      and the timesheet is attached after the invoice.
- [ ] Tick the same log on a new invoice: "Already billed" warning, and a question before export.
- [ ] Invoices tab: Mark paid…, Invoice again, Delete draft, filters, overdue shown in red.
- [ ] Copy email text pastes a ready message.

## Look and layout
- [ ] Business profile › Layout: presets switch; dragging a block snaps it into a new spot; preview updates live.
- [ ] Theme button switches light/dark; Settings › Appearance "Match Windows" follows Windows.

## Docket hooks
- [ ] From Docket: Open Ledger, and "Make a PDF in Ledger…" opens that log (also when Ledger is already open).
- [ ] After closing, `%APPDATA%\Docket\shared.json` has a "categories" list (names only).

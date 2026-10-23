# Slice 0 spike: the PDF document engine (ReportLab)

**Date:** 2026-10-12 · **Verdict:** ReportLab 5.0.1 with `[shaping]` is fit to be the only PDF engine. Latin, Greek, Cyrillic, € ₹ £ and Devanagari all render correctly. Long tables paginate with the header repeated, and output is byte-for-byte deterministic. Text extraction of Devanagari has known visual-order artefacts (see Limitations).

**Environment:** Windows 11, Python 3.14.6, reportlab 5.0.1, uharfbuzz 0.56.3, pypdf 6.20.0 (dev only). Fonts are Noto Sans Regular/Bold/Italic and Noto Sans Devanagari Regular/Bold, static TTF, SIL OFL (`backend/app/core/documents/fonts/OFL.txt`).

## How to reproduce

```
cd backend
uv run python -m app.core.documents.spike          # writes docs/evidence/slice-0/pdf-spike.pdf and prints a JSON report
uv run pytest tests/unit/test_documents.py -q       # 35 tests
powershell -NoProfile -ExecutionPolicy Bypass -File ..\docs\evidence\slice-0\rasterise-pdf.ps1 `
  -Pdf ..\docs\evidence\slice-0\pdf-spike.pdf -OutDir out -Pages "1,6,19,20" -Width 1240
```

`rasterise-pdf.ps1` renders pages with the Windows built-in PDF renderer (`Windows.Data.Pdf`). That renderer is independent of ReportLab, so the shaping check does not rely on ReportLab grading its own output.

## What the spike document contains

`pdf-spike.pdf` is a 20-page "Quotation" with a DEMO watermark. All of its data is demo data.

- **Header band on every page:** a generated monogram logo, plus a Unicode legal name that mixes Latin and Devanagari (`Crown Décor Private Limited · क्राउन डेकोर प्राइवेट लिमिटेड`). Below that come the address lines (one in Devanagari), contacts, GSTIN, and the title/number/date/customer/currency block.
- **Footer on every page:** the footer terms (`&` escaped), and `SPIKE-0001 · Page X of 20`.
- **Bill to / Ship to blocks:** `Nordhaus Møbler ÅB`, `Łódź · Ελλάδα · Москва`.
- **Glyph line:** `€ ₹ £ Ł Ω Ж`. The INR grouping line shows `₹1,23,456.00` and `₹1,23,45,678.90`.
- **Devanagari lines:**
  - `क्राउन डेकोर`, `नमस्ते`, `श्रीमती प्रिया शर्मा`, `हिन्दी` and `द्वार कृष्ण ट्रक क्षमा त्रिकोण ज्ञान`.
  - A mixed-script word with no spaces, `Crown क्राउन-Decor, ₹१,२३,४५६`.
  - Bold Devanagari, `प्राइवेट ट्रक`.
- **The 150-line table:**
  - Columns are #, Product (bold SKU plus a long name, sometimes on two lines), Details, Unit price, Qty and Total.
  - Rows 40 and 95 carry descriptions of about 3,000 characters, each taller than a page.
- **Totals blocks:** two of them. One is the table total. The other is the legacy surcharge example: €4,800.00 + €400.00 = €5,200.00.
- **Other blocks:** numbered terms and the three challan signature boxes.
- **Cut-plan board:** a 2440 × 1220 mm board with a 5 mm trim margin. It has coloured pieces, rotated pieces with corner marks, an overproduction ("extra") piece, a tiny piece and a dashed offcut.

## Results (spike JSON report, final run)

| Check | Result |
|---|---|
| Pages | 20. The table runs from page 1 to page 18, the totals, terms and signatures are on page 19, and the board is on page 20 |
| `Page X of 20` on every page | yes |
| Table header row on every table page | yes, exactly once per page (`test_long_table_spans_pages_with_one_header_per_page`) |
| All 150 SKUs present in the extracted text | yes |
| ~3,000-character descriptions complete after splitting across pages | yes. The Details column's text was extracted by x-position and compared in full |
| € ₹ £ Ł Ω Ж and the four Latin/Greek/Cyrillic names extracted | yes, all |
| INR Indian grouping printed | yes |
| Devanagari extracted exactly | `क्राउन डेकोर`, `नमस्ते`, `प्राइवेट ट्रक` (bold) |
| Devanagari: every source character recovered | yes for all five samples. Order is visual where noted below |
| Private-use (U+E000–F8FF) characters in the extracted text | none |
| Mixed-script word (spaces ignored) | yes |
| Fonts | NotoSans-Regular, NotoSans-Bold, NotoSansDevanagari-Regular and NotoSansDevanagari-Bold, all embedded as `/FontFile2` subsets. No Helvetica or Times references remain |
| Deterministic | yes. Two builds in one process give identical bytes. Two separate processes give the same output, sha256 `83e6323d38c2e06a905c9fc28e192e5847cc9befbc2473f3301cec2f9a2f8f6d`. So does a process that first rendered a different Devanagari document (`test_shaped_output_does_not_depend_on_render_history`) |
| Build time (150 rows, 20 pages) | 0.4–1.1 s warm, 0.6–2.8 s cold, depending on machine load from parallel lanes |

## Devanagari shaping: what was verified

1. **Visual check.** Page 1 was rasterised with the Windows renderer at 300 dpi. The crop is `pdf-spike-devanagari.png`. Every form renders correctly:

   | Feature | Example |
   |---|---|
   | Conjuncts | क्र, ष्ट, ष्ण, क्ष, ज्ञ, त्र |
   | Stacked conjunct | द्व |
   | Half forms | स्त in नमस्ते, न्द in हिन्दी |
   | Pre-base i-matra drawn before its consonant | हि, प्रि, त्रि |
   | Reph above the following consonant | शर्मा |
   | Rakar | ट्र |
   | Vowel sign under the consonant | कृ |

   The mixed word and the bold Devanagari also render correctly.
2. **Glyph check.** `test_devanagari_is_shaped_into_conjunct_glyphs` asserts that the embedded Devanagari font's ToUnicode CMap maps one glyph code to the three characters `क ् र` (`<0915094D0930>`). That mapping exists only when HarfBuzz substituted the k_ra conjunct glyph.
3. **Text check.** pypdf recovers every character of every sample. The checks are `devanagari.*.all_characters_recovered` in the report, and the tests `test_glyphs_names_and_devanagari_extract_with_embedded_fonts` and `test_pre_base_matra_characters_are_all_recovered`.

## Library gaps found and closed in `app/core/documents`

- **Mixed-script words were garbled.** ReportLab shapes a whole word with the font of its first fragment. In `क्राउन-Decor`, the Latin letters came out as wrong glyphs.
  - `fonts.py` installs a hook that shapes each same-font run of a word separately.
- **Conjuncts extracted as private-use code points (U+E000…).** Search and copy/paste of Hindi text broke.
  - The hook records the source characters of each shaped cluster.
  - The ToUnicode CMap writer maps each private glyph back to those characters, for example k_ra → `क्र` and t_ra → `त्र`.
  - Clusters that hold several private glyphs (`त्रि`) are attributed using the font's glyph names: `iMatra*` → `ि`, `reph` → `र्`, `rakar` → `्र`.
  - Bfchar blocks are also kept to 100 entries or fewer, as the PDF specification requires.
- **The header repeated mid-page.** `LongTable(splitByRow=1, splitInRow=1)` first split between rows. It then split the next row into the space left on the same page, which printed the header a second time mid-page.
  - `tables.LineTable` splits between rows only. A row that does not fit moves to the next page whole.
  - A row is broken across pages only when it is taller than an empty page.
- **`keepWithNext` on a heading pushed the whole 150-row table to page 2.**
  - `section_heading` now uses `CondPageBreak(heading + 25 mm)` instead.
- **Non-embedded `Helvetica` and `Times-Roman` were referenced.** They came from empty table cells and the graphics renderer's default font.
  - Every table starts from `base_table_style()` with an embedded font.
  - Drawings set `initialFontName`.
- **A `<font face>` tag reset bold.** `script_markup(..., bold=True)` names `LK-Deva-Bold` directly, and `para()` does this automatically for bold styles.
- **Opaque content could hide the watermark.** The watermark is drawn last, over the content, at 7% opacity, together with "Page X of Y" in the deferred-page canvas.

## Limitations (honest status)

- **Extraction order of Devanagari text.**
  - A ToUnicode map cannot reorder text, so text extraction and copy/paste follow visual order. Pre-base matras come out before their consonant: `हिन्दी` → `िहन्दी`, `प्रिया` → `िप्रया`. Reph comes out after its consonant: `शर्मा` → `शमार्`.
  - pypdf also inserts spurious spaces around some marks: `कृष्ण` → `क ृ ष्ण`.
  - Rendering is correct. Only machine-read text is affected.
  - Fixing this needs `/ActualText` spans, which ReportLab does not emit. **Tests that compare extracted Devanagari must use samples without pre-base matras or reph, or compare character multisets.**
- **Scripts covered.** Only Latin, extended Latin, Greek, Cyrillic and Devanagari are covered. Gujarati, Bengali, Tamil and similar scripts would print as empty boxes.
  - `fonts.coverage_gaps(text)` reports such characters so callers can warn.
  - Adding a script means adding its Noto TTF and a run rule in `fonts.py`.
- **Missing faces.** There is no bold-italic face, so it maps to bold. There is no Devanagari italic, so it maps to regular.
- **Board-drawing labels are drawn unshaped.** `reportlab.graphics` strings have no HarfBuzz path, so labels should stay part codes.
- **Fixed metadata dates.** Invariant mode fixes the PDF `CreationDate`/`ModDate` to 2000-01-01 and fixes the file ID. This is the price of reproducible bytes and of comparing sha256 for issued revisions. The document's real date is printed in the header.
- **Builds are serialised.** ReportLab's font and shaping state is process-global, so PDF builds take `fonts.RENDER_LOCK` and run one at a time per process. At this business's volume that costs little. Large batch rendering belongs in the worker.
- **Page space.**
  - A row too tall for the remaining space starts on the next page, which leaves white space at the bottom of the previous page. Only rows taller than a whole page are split.
  - A totals block never splits. When it does not fit under the last row it moves to the next page on its own, as it does in the spike.
- **Rasterisation is a manual step.** It relies on the Windows PDF renderer, so it is not part of the automated suite. The automated suite checks shaping through the ToUnicode glyph mapping.

## Evidence files

- `pdf-spike.pdf`: the spike document.
- `pdf-spike-page-1.png`: page 1, with the header band, Unicode, the Devanagari block and the start of the table.
- `pdf-spike-page-6.png`: row 40 (taller than a page) continued from page 5 after an in-row split, with the header repeated once, ending at `END-OF-ROW-40`. Rows 41 onwards start on page 7.
- `pdf-spike-page-19.png`: the table totals, the surcharge example totals, the terms and the signature boxes.
- `pdf-spike-page-20.png`: the cut-plan board drawing.
- `pdf-spike-devanagari.png`: a 300 dpi crop of the shaped Devanagari lines.
- `rasterise-pdf.ps1`: the rasteriser used for the PNGs.

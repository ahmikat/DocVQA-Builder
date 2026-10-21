# Taxonomy v4 reference

The machine-readable source of truth is [bndocvqa/models/taxonomy.py](../bndocvqa/models/taxonomy.py). The prompt, response parsing and exports all read from it. For fictional worked examples of every axis, see [axis_definitions_and_example_v4.md](../axis_definitions_and_example_v4.md).

## Codes

### B-axis: Evidence and verification

| Code | Name | Definition |
|---|---|---|
| B01 | Direct evidence reading | Identify a specific fact or number explicitly stated in the document. |
| B03 | Evidence sufficiency and abstention | Determine that the required information is absent after reviewing the relevant complete document. |
| B04 | Claim verification | Classify a specific claim as supported, contradicted, or insufficient information. |

### C-axis: Document capabilities

| Code | Name | Definition |
|---|---|---|
| C01 | Structural locating and layout | Understand headings, subsections, footnotes, checkbox states, or layout hierarchy. |
| C02 | Table interpretation | Correctly associate table row headers, column headers, units, and cell values. |
| C03 | Charts and infographics | Interpret graphical bars, pie charts, symbols, and legends. |
| C04 | Maps and spatial relations | Understand directions, proximity, boundaries, and spatial relationships. |
| C05 | Counting | Count a clearly defined set of items under a specified rule rather than copying a printed total. |
| C06 | Filtering and set selection | Identify all entries satisfying a specified condition. |
| C07 | Comparison and ranking | Compare two or more values and identify maxima or minima, including ties. |
| C08 | Arithmetic and aggregation | Perform addition, subtraction, averaging, or other calculations using document values without assuming undocumented taxes or fees. |
| C09 | Temporal reasoning | Calculate durations, travel times, remaining days, or differences between dates and times. |
| C10 | Units and numerical normalization | Convert units such as crore to lakh or millimetres to centimetres. |
| C11 | Conditions and exceptions | Determine eligibility or applicability using documented conditions and exceptions. |
| C12 | Entity and record binding | Match information to the correct person, organization, or record. |
| C13 | Cross-element association | Combine information such as a table and its footnote, or an image and its textual condition. |
| C14 | Bounded synthesis | Combine specific information from multiple sections or paragraphs into a concise answer. |
| C15 | Amendment and conflict reconciliation | Determine the final applicable value or rule when original and amended provisions conflict. |

## Assignment rules

- Every question has exactly one `primary_axis`.
- `sub_axes` lists only genuinely additional capabilities. It never repeats the primary axis, and it never contains B03 or B04, because those change the answer semantics.
- Do not force axes. A document that has no chart gets no C03 question.
- `axis_name` is derived from the code at export time, so the name and code can't drift apart.
- Items Gemini returns with an unknown axis are dropped; invalid sub-axes are removed.

## Answer semantics by axis

| Primary axis | `question_format` | `question_type` | Options | Correct answer |
|---|---|---|---|---|
| B03 | `mcq5` | `abstention` | A–E | exactly `প্রদত্ত নথিতে উল্লেখ নেই` |
| B04 | `verify3` | `claim_verification` | fixed A=`সমর্থিত`, B=`খণ্ডনকৃত`, C=`অপর্যাপ্ত তথ্য` | one of the three |
| all others | `mcq5` | `answerable` | A–E | one document-grounded option |

**B03** scope is the page. Gemini sees one page per request, so an abstention question asks for something a reader could reasonably expect *this page* to state but that is certainly not on it. Missing doesn't mean zero.

**B04** uses a separate three-option schema. The researcher chose this on 2026-10-21 so that two artificial outcomes don't have to be invented to fill five options. B04 is scored separately from five-option accuracy, because its chance level is 33%, not 20%. The question must state one specific claim. `খণ্ডনকৃত` requires the document to state something incompatible with the claim. Absence of evidence is `অপর্যাপ্ত তথ্য`.

**Abstention distractor policy.** If `প্রদত্ত নথিতে উল্লেখ নেই` appeared only in B03 questions, its mere presence would reveal the answer. So it is also used as a distractor in a configurable share of answerable MCQs (default 30%). Which questions get it is decided deterministically from the question ID.

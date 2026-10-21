---
title: PKVC Report 06: Parser Validation Report
owner: Fazle Core Admin
status: archived
last_verified: 2026-06-24
runtime_index: false
---

# PKVC Report 06: Parser Validation Report

> **Pre-unification schema note.** Table names in this document refer to the
> pre-unification schema. See `audits/prefix_unification_2026-10-21.md` for the
> current table names.
- Date: 2026-06-21
- Scope: Production parser behavior vs KB documentation

## Result
- Status: PARTIAL

## Parsers Covered in Evidence
- Escort order parsing family
- Attendance parser
- Release confirmation parser
- Payment ingest parser
- Admin shorthand parser
- Tokenization and intent fallback parsing behaviors

## Validation Findings
- Production parser behavior is identifiable and testable.
- KB representation is incomplete for regex boundaries, unsupported input formats, and deterministic fallback behavior.

## Required Documentation Additions
- Input and output contracts per parser
- Regex and keyword extraction references
- Error and unsupported-format examples
- Decision logic for ambiguous input

## Parser Conclusion
Parser knowledge is partially documented and not yet PKVC-complete.

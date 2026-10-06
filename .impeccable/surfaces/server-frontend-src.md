---
version: 1
slug: "server-frontend-src"
primary_target: "server/frontend/src"
related_targets: []
---

# Meters webapp: surface brief

Scope: device list (`#/`) and device page (`#/device/<id>`) in server/frontend/src.
Visitor mode: Operate. Regular consumers check usage and whether a meter is online, in short glances on a phone.
Task: find the current total and trend within seconds; see online state; switch period; step through time windows.
Constraints: no brand binding; data, copy, and behavior unchanged; phone width first; WCAG AA both themes.
Replaces the previous warm consumer direction (user request: complete change).

## Direction contract

THESIS: Meter readings printed like a reference plate. Information is set in type on paper, and color appears only inside framed plates. It refuses the rounded card dashboard.
OWN-WORLD: Warm uncoated paper ground, engraving-black ink, hairline rules and a double rule at the head. Ultramarine ink is used only inside the framed chart plate; vermilion marks only the reset note. Literata serif throughout, tabular lining figures for every number.
STORY: The visitor reads the total as a figure set on a page, sees the device's state as a printed mark, and steps through time with printed controls. They trust it because it looks like a record.
FIRST VIEWPORT: Head with double rule: device name left, status mark right. Beneath, the period total set very large in serif, with its unit and the net difference, inside a framed plate. Period tabs as a text index with an ink underline on the selected item. Window navigation as printed arrows around the date. The chart sits in a second framed plate.
FORM: Rare-words lexicon-shoulder-and-plate challenger (catalog id rw-lexicon-shoulder-and-plate). Adapted: the shoulder becomes a gutter, the thumb index becomes the period index, guide words become the head rule labels. Seed key 0a35cbf8.
FINISH: unreviewed and undocumented is unfinished; this build ends with the finish review, the verdict, DESIGN.md, and every shipping raster carrying its provenance.

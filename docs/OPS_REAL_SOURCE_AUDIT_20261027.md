# OPS-P0 | Original-source audit and scratch-flag anomaly, 27 Oct 2026

**Status: ORIGINAL_PDF_TO_STARTLIST_IDENTITY_617_617; SCRATCH_STATE_CONFLICT;
DAY_COMPLETENESS_NOT_VERIFIED.** This is empirical evidence from the *actual*
public Collector archive, not from the synthetic source-contract suite.

## Source chain / immutable identifiers

- GitHub Collector [actual run 40487116264](https://github.com/Maremoo2/rikstoto-program-collector/actions/runs/40487116264),
  branch SHA `750967b8`, source artifact **12726250010**,
  `rikstoto-morning-programs`.
- Exact original ZIP (as downloaded for this audit) SHA-256
  `dc449df6f3059c10d21a568630e59027819d32fd4f7f2f72d296261aaba27b9b`.
- Run ID: `20261027T101634951984Z`; manifest created
  `2026-10-27T10:16:34.952304+00:00`.
- Original sources: six unique physical meeting PDF byte files and six
  separately archived `/api/racedays/{meeting}/starts` JSON files,
  plus the `X1_NR` composite PDF **excluded from physical totals**.

### Direct original-PDF check (not merely re-reading parser output)

With PyMuPDF, reopen all **six PDF files** directly, group each page under
the printed `Løp N` or page-initial numeric race heading (retaining
continuation pages), extract the uppercase printed horse header
`<start number> <HORSE NAME>, <driver>`, and compare that horse identity
to the independently archived official starts-JSON **in the exact same
physical meeting, race number and start number**, allowing Unicode
case/diacritic normalization only. This is a second extraction path
independent of Collector's `parse_extended_pdf` implementation, but
both files still originate from Rikstoto; it is **not** an independent
global calendar or a semantic history-value audit.

| Physical track | Meeting ID | PDF races | Header horses = API runners | Raw API isScratched=true |
| --- | --- | ---: | ---: | ---: |
| Bjerke | BJ_NR_2026-10-27 | 8 | 95 = 95 | 2 |
| Deauville | F1_NR_2026-10-27 | 8 | 100 = 100 | 2 |
| Gelsenkirchen | F2_NR_2026-10-27 | 7 | 69 = 69 | 13 |
| Paris-Vincennes | F4_NR_2026-10-27 | 8 | 116 = 116 | 1 |
| Boden | S1_NR_2026-10-27 | 10 | 123 = 123 | 3 |
| Axevalla | S2_NR_2026-10-27 | 10 | 114 = 114 | 5 |
| **Total** | **Six physical tracks** | **51** | **617 = 617** | **26 raw flags, NOT verified actual scratches** |

The 51/51 race keys and all 617/617 PDF horse-header/API
number/name identities match in the archived 27 October six-meeting
universe. **These numbers are a within-archive validation only**.
There are no observed missing/extra original PDF headers in that universe.

### Real P0 failure: Gelsenkirchen all-scratch flags

The archived source `F2_NR_2026-10-27/starts.json`, captured around
10:17 UTC, reports:

- Race **6**: **5/5** runners `isScratched=true`.
- Race **7**: **8/8** runners `isScratched=true`.

But independent published results show these **two races actually
took place**. Gelsenkirchen R2C6 lists winner #4 Klaus Von Herten
and the five named finishers:
https://turfma.com/pmu-resultats-du-jour/gelsenkirchen-r2c6-27-10-2026/
The completed R2C7 lists winner #5 Nothello and eight participants:
https://www.geny.com/course/1693830-2026-10-27-gelsenkirchen-auf-wiedersehen-am-8-11-im-gelsentrabpark/arrivee-rapports

This disproves the claim that all 13 flags establish verified
withdrawals. It does **not** independently establish each runner's true
scratch status *as of the earlier source capture*, nor does it justify
retroactively setting all the original source booleans to `false`.
These 13 are **raw API true flags with unverified semantics**. The
remaining 13 raw API true flags in other meetings have **not** gained
independent withdrawal verification merely because they are outside
this conflict.

The original `startlist_audit.reconcile_startlist()` accepted an exact
PDF↔API identity match even when every runner in a race was flagged
scratched. It then assigned `SCRATCHED_AS_OF_SNAPSHOT` to the whole
field and counted the flag values as `confirmed_scratches`.

### Fail-closed corrective contract

When a race has a correct full identity match yet *all* runners have
`isScratched=true`, Collector now:

- preserves original `starts.json` bytes and all `true` source flags;
- records `ALL_RUNNERS_SCRATCH_FLAG_REQUIRES_INDEPENDENT_CONFIRMATION`
  with race number and flagged runner count;
- sets horse `scratch_state=UNKNOWN_ALL_RUNNERS_FLAGGED`,
  `scratched=null`, with separate raw flag candidates;
- sets `scratch_verification=UNVERIFIED_ALL_RUNNERS_FLAGGED`,
  unknown active/scratched counts, an explicit QA warning and a
  `PARTIAL_OR_UNVERIFIED` meeting audit;
- does **not** count them as verified withdrawals, does not silently
  mark them active, and does not make the full race eligible for
  source-ready Pre-Watch or BET.

Normal mixed active/scratched race fields retain existing behavior.
The source archives are never rewritten or historically re-scored.

## Other unclosed full-day issue: Jägersro

The independent official Jägersro site lists 27 October 2026 races
https://www.jagersro.se/trav-och-lopp/trav/bevaka-hemmalaget/
and Sulkysport lists eight races from 17:45–20:22
https://sulkysport.se/lopp/jagersro-2026-10-27/.

**Jägersro is absent from the archived Rikstoto SPA and
`/api/racedays` meeting lists.** This proves a difference between
the broader Swedish racing calendar and the captured Rikstoto-offered
meeting subset; it does **not** alone prove a Rikstoto discovery bug,
because not all Swedish tracks must be offered in this market.
The original `/api/racedays/dates` response was successful but empty,
so independent **Rikstoto-offered** complete-day coverage has not been
certified. Preserve `DATE_RANGE_API_NO_TARGET_MEETINGS` and
`CROSS_MEETING_COMPOSITE_NOT_UNIQUE_TRACK` warnings.

## Exact raw source SHA-256

| Meeting | Original PDF SHA-256 | Original starts.json SHA-256 |
| --- | --- | --- |
| BJ_NR | `76ac03fd83ae8a610d6bdd9592298110aed851c9e1401e2fa8befcafe5cce0ba` | `01e37ac1275e95ed3a6a19c0cd0a1ed04ed0df42baf7240d7b2e94cc66b7a136` |
| F1_NR | `233426af6adfc8f6949272fd7bf3a3a7706c073eea339586637010678d124739` | `bf8c914f481ae39071ac571edd48f71ec79af7e0c7bb3c87e4b9d870692667fe` |
| F2_NR | `1cd2d2dee7dc29ca53c11d851bf09cac37a6ae95ebea5c0d37128707fb040797` | `a85d4cd711057bddc7f446b85df4571aee976fbaf6eec777d28f997044e6d71d` |
| F4_NR | `815992588fceaeae94433d40c2aa026da7456629cbc71a81702e9f1548d126e4` | `e45dc7f1f9bc3eb907c47d787eacd1c4fff38df2af3e27085516ab4cd4514b87` |
| S1_NR | `dcc98c530e41af6f6c7c40d1c941d431b07a21ca0f166ca606a9f70c9ccc3b2b` | `3c60d1279e8ccf6094f1677c4812b3e6affdf5120a4dcff375b4f464b07f5d45` |
| S2_NR | `767909c0e988f4b4f17bb90a0a52c75660c2e012fad43b14c3092444445c2336` | `be3f294340d8f09834a474b7cbbc744309ef595bd81e43bf0117636e2abab3c0` |

## What has NOT been proven or changed

No full market-wide day completeness, no official prestart scratch
semantics for F2 race6/7, no earlier point-in-time feature correctness,
no historical result parser gold, no standalone WIN pool, no real
A-WATCH qualification and no betting probability or edge are
established by this audit. Every old source file and prior snapshot
is left intact; the correction is for **future** source admission.

**Acceptance state:** `PDF_API_IDENTITY_617_617` (narrow source fact),
`SCRATCH_STATE_UNVERIFIED` (two races), `DAY_COMPLETENESS_NOT_VERIFIED`.
`BET_BLOCKED` always.

Next high-value step under Collector issue #11: independently verify the
**Rikstoto-offered meeting universe** rather than equating it to every
Swedish race; then adjudicate the source semantics and preserve a
separate source-readiness denominator. No further synthetic Phase B
infrastructure is needed before that evidence.

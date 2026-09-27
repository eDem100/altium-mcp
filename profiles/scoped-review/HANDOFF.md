# Handoff - 2026-09-27

Status: stopped for the day at the user's request. Implementation is incomplete.
No original CAD document was modified and no production signoff was issued.

## Completed and observed

- The local scoped deployment exposed 19 tools, retaining the original nine
  read tools. Project identity no longer depends on which tab is focused.
- Live Messages capture succeeded: 15 no-driving-source warnings and one
  compile-success message, with no error rows. Messages carried only document
  basenames, so the validation run remained user-attributed. No validation or
  message clearing was launched by the reader.
- A schematic was read by its path while the PCB stayed focused. Inactive PCB
  and closed-document load behavior still require dedicated native evidence.
- Four bounded point captures completed in approximately 6-7.5 seconds each.
  These are smoke observations, not latency guarantees or p95 acceptance.
- A top-layer SMD pad pair measured 2.50000008 mm between centers and
  2.22060008 mm between native edges. This does not verify all shapes/layers.
- One experimental copy was created through MCP. Its 17 initial saved files
  matched the source hashes. Four production-output references were relocated
  inside the copied project. No copied PCB geometry was edited.
- Installed SDK 1.5.0 decoded decimal-string IDs into integers before validation.
  The binding accepts strings or StrictInt and checks exact bounded addresses
  against the snapshot before native access. No package upgrade was performed.

## Failures and recovery lessons

A full native capture returned about 15 MB only after the 120-second MCP limit,
temporarily occupying the Designer UI. The validated late response was retained
as diagnostic evidence, not accepted as a timely MCP snapshot. Both exact
timeout cases were archived before clearing their correlated markers. The
reader now decodes at most 100 selected records per page; avoid full dumps for
ordinary questions.

An invalid schematic Text getter was corrected using typed interfaces and
ISch_Port.Name. A separate workspace-focus check incorrectly blocked reads
when another project retained focus. The final selector uses the manifest
target among open projects and the exact PCB path.

## Checkpoint packaging

The private deployment remains separate from this publishable profile. Private
design files, BOMs, raw messages, snapshots, user paths and recovery records are
excluded. Scripts use the profile directory and synthetic policy/config examples.
The duplicate identical generated target function was reduced to one declaration,
and the example output-folder name is derived from the project stem. This
packaging has host/SDK validation; it has not been installed as a replacement
for the running deployment.

## Next goals, in order

1. Compare the root server's newer native-service transport (28f3723) and stackup
   fix (add84e4) with this profile. Preserve the current upstream/default server;
   decide how to combine its transport with scoped policy/correlation/recovery
   guarantees. Do not enable a second uncontrolled execution channel.
2. Finish document access by explicit project/sheet identity, including scoped
   loading of requested closed schematics and native inactive-PCB acceptance.
   Improve message attribution using confirmed document/run provenance.
3. Extend targeted reads: compiled connectivity, effective rules (including
   multiple Matched Length constraints), board outline/cutouts, pad suppression,
   VIA stacks, courtyard/assembly roles, stackup/material/impedance data and
   manufacturing output provenance. Missing fields must remain explicit.
4. Add a verified coherent multi-page baseline suitable for controlled edits.
   Independent point-query snapshots currently cannot satisfy this requirement.
5. On an isolated copy, implement bounded native analysis completion, DRC
   coverage/exclusions and export/repour evidence. Do not turn a zero count
   without coverage into a passing result.
6. Implement and test native transactional text placement first, then permitted
   component/rule changes: full preflight, readback, backup, undo/restore,
   partial failure and timeout reconciliation. Current write/analysis handlers
   deliberately return blocked; host simulation is not native acceptance.
7. Compare a concrete before/after package and obtain explicit authorization
   before applying that package to the original. Never replace the original
   PCB wholesale with the experimental file.

The separate processor-module/routing-learning project remains out of scope.

## Validation at checkpoint

60 host contract tests and 3 installed-SDK argument-binding tests passed in the
working deployment. The published profile is also tested before commit. Native
observations above apply to that deployment/configuration, not every host.
The pre-existing main.py invalid-escape SyntaxWarning remains visible.

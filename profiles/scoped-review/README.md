# Scoped review bridge - development checkpoint

This optional profile preserves the scoped bridge work from 2026-09-27. It
does not replace the repository's root server or activate itself on install.
The source was adapted from upstream commit
16f42203e94034daf078b964de6d7ddf741ea816. The root server has newer work; see
HANDOFF.md before attempting integration.

## Implemented

- Versioned project/document allowlist with one explicit experimental copy.
- Exact manifest project and PCB path lookup independent of UI tab selection.
- Bounded PCB/schematic query pages, exact component filters and explicit
  incomplete-data reporting. No automatic compile, DRC, repour or save.
- Existing Messages capture with project attribution and ambiguous-name flags.
- Snapshot provenance, source hashes, session binding and stale-data rejection.
- Snapshot-bound pad-center and native primitive-edge measurements.
- Correlated serialized requests and fail-closed timeout/recovery handling.
- Saved-file copy/hash proof, package preflight and host fault-injection tests.

Native analysis and controlled writes remain disabled. A page is not a complete
project snapshot. Independent page captures must not be treated as one proven
global epoch. Full inventory is required for route or edit claims.

## Configuration

The committed policy is an example with synthetic paths and document names.
No board, schematic, BOM, message export, private runtime configuration,
credential, environment or CAD snapshot is included.

1. Use an existing compatible Windows Python environment. This profile was
   exercised with mcp 1.5.0 and its existing dependencies. Do not run the root
   server and this profile against the same exchange directory concurrently.
2. Copy server/pilot_policy.example.json to ignored server/pilot_policy.json.
   Set exact local project, working PCB, member documents, executable, runner,
   private exchange and results paths. Keep original_write_enabled false.
3. Provision and protect the private exchange directory. The profile does not
   provision its ACL automatically. Do not reuse the root server's public
   exchange. The runner path must not contain spaces for this launch contract.
4. Run scripts/Prepare-AltiumBridgeV2.py --generate after changing the policy.
   This regenerates native allowlists, target identity and the exchange path.
5. Adapt mcp-config.example.toml in the intended client. No global client
   configuration is changed by these files.
6. After source/policy changes, reload the MCP process and the runner source.
   Check capabilities before native calls. Do not retry an uncertain timeout
   until native completion/stop and correlated recovery evidence are known.

The profile opens only the exact allowed PCB when a PCB operation needs it;
it does not select arbitrary UI documents or silently fall back to another
project. Schematic loading/targeted selection still has coverage gaps.

## Verification

From this profile directory, using existing interpreters:

```text
python -B scripts/Test-AltiumBridgeV2.py
python -B scripts/Test-AltiumMCPArgumentContract.py
```

The first suite uses standard-library host fixtures. The second requires the
installed MCP/Pydantic environment and tests actual SDK argument binding without
starting an MCP server or Altium. Neither is CAD acceptance.

See HANDOFF.md for observations, limitations and the next engineering goals.

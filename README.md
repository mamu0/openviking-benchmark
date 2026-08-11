# OpenViking Benchmark

Support material to reproduce, from scratch, the evaluation of
[OpenViking](https://github.com/volcengine/OpenViking) v0.4.13 as a
persistent knowledge and memory layer for coding agents.

The repository contains the test corpus, the measurement harness, and the
setup scripts. It contains no keys: the configuration must be completed by
hand starting from `ov.conf.example`.

## Contents

| Path | Description |
|---|---|
| `corpus/` | 4 test documents split across two teams, used as a knowledge base |
| `harness/facts.json` | The 3 facts to retrieve, with question and grading criteria |
| `harness/measure.py` | Measurement harness, phases `seed`, `cold`, `control`, `judge`, `report` |
| `harness/measure_tiers.py` | Token count for the L0, L1, and L2 tiers |
| `harness/results.json` | Results from the minimal harness |
| `harness/results-copilot-cli.json` | Measurement in AIU on a real coding agent |
| `scripts/setup.sh` | Installation, configuration, and server startup |
| `ov.conf.example` | Configuration template with placeholders |

## Prerequisites

- Python 3.10 or later
- An OpenAI-API-compatible endpoint exposing a generation model and an
  embedding model. The original test used Azure AI Foundry with
  `gpt-5-mini` and `text-embedding-3-small`, reached through the
  `/openai/v1` path with `Authorization: Bearer` authentication.
  Ollama running locally is an alternative.

## Quick start

```bash
git clone <this-repo> openviking-benchmark
cd openviking-benchmark
./scripts/setup.sh          # first run: creates ~/.openviking/ov.conf and exits
$EDITOR ~/.openviking/ov.conf   # fill in the placeholders
./scripts/setup.sh          # second run: verifies, starts, shows status
```

Two steps are not obvious from the official documentation and are already
included in the script: `ov language en` must be run at least once, and
`~/.openviking/ovcli.conf` must exist, otherwise every `ov` command fails.

## Ingesting the corpus and detail tiers

```bash
cd ~/openviking-lab
.venv/bin/ov add-resource <repo-path>/corpus --wait
.venv/bin/ov tree viking://resources -L 3
.venv/bin/ov abstract viking://resources/corpus/team-alpha/prd-checkout.md   # L0
.venv/bin/ov overview viking://resources/corpus/team-alpha/prd-checkout.md   # L1
.venv/bin/ov read     viking://resources/corpus/team-alpha/prd-checkout.md   # L2
```

The `ov grep` command requires an explicit scope and does not work from the
root: use `ov grep <pattern> --uri=viking://resources`.

To count tokens across the three tiers:

```bash
.venv/bin/python harness/measure_tiers.py
```

## Measuring cross-session retrieval

The harness compares two arms on the same question: one with access to
OpenViking through MCP, one with no memory at all. Answers are graded by an
LLM judge with a strict rubric, not by keyword matching, which produced
false positives.

```bash
export AZURE_OPENAI_BASE="https://<resource>.cognitiveservices.azure.com/openai/v1"
export AZURE_OPENAI_KEY="<key>"
export AZURE_OPENAI_MODEL="gpt-5-mini"

.venv/bin/python harness/measure.py seed      # populates memory, not measured
.venv/bin/python harness/measure.py cold      # arm with OpenViking
.venv/bin/python harness/measure.py control   # control arm
.venv/bin/python harness/measure.py judge     # grades the answers
.venv/bin/python harness/measure.py report    # summary table
```

Fresh tokens are computed as `usage.prompt_tokens` minus
`prompt_tokens_details.cached_tokens`, so they come from the provider's own
accounting rather than an estimate.

The harness is deliberately minimal. A full coding agent carries a very
large system prompt, which would swamp the marginal cost of retrieval and
make the measurement meaningless.

## Testing against a real coding agent

To connect OpenViking to GitHub Copilot CLI without touching the global
configuration:

```bash
copilot --additional-mcp-config '{"mcpServers":{"openviking":{"type":"http","url":"http://127.0.0.1:1933/mcp","headers":{"X-Api-Key":"<user-key>"},"tools":["*"]}}}' \
        --allow-tool 'openviking' \
        -p "<question>"
```

## Multi-account isolation test

```bash
# in the config file: auth_mode: api_key and root_api_key set
curl -s -X POST http://127.0.0.1:1933/api/v1/admin/accounts \
     -H "X-Api-Key: <root_api_key>" -H 'Content-Type: application/json' \
     -d '{"account_id":"team-alpha","admin_user_id":"alice"}'
```

The user key returned in `result.user_key` is used in the `X-Api-Key`
header. With two separate accounts, verify that the tree shows only its own
space, that semantic search does not return URIs from the other account,
and that direct access to another account's URI returns
`PERMISSION_DENIED`.

## Caveats

- Do not commit `~/.openviking/ov.conf`, `ovcli.conf`, or user keys.
  `.gitignore` already excludes these paths.
- The `ov add-memory` command in `api_key` mode responds `OK` without
  writing anything. To write memory, use the MCP tool `remember`, which
  requires the `messages` field.
- OpenViking is distributed under the AGPL-3.0 license. Assess its
  obligations before exposing it as a network service.

## Configuration notes

The `~/.openviking/ov.conf` file is in **JSON** format, not YAML, despite
the `.conf` extension suggesting otherwise. The actual schema uses
`embedding.dense`, not `embedding` at the top level.

The `vlm.reasoning_effort` key is read by the code but not accepted by the
validation schema: if set, `openviking-server doctor` fails with
`Unknown config field`. It must be omitted.

To switch to multi-account mode, set under `server`:

```json
"auth_mode": "api_key",
"root_api_key": "a-key-of-your-choice"
```

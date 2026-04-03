# Competitive Comparison: `dixp` vs Other Python DI Libraries

Status: April 3, 2026

This document is intentionally strict about claims.

- It lists verified competitor positioning from official project pages.
- It lists locally verifiable `dixp` capabilities from this repository.
- It does not invent head-to-head performance numbers that were not measured.

As of April 3, 2026, this repository now includes:

- installed competitor libraries in a local `.venv`
- a reproducible benchmark harness in `benchmarks/run_di_benchmarks.py`
- benchmark workflow notes in `benchmarks/README.md`
- a local snapshot in `benchmarks/latest-results.json`
- a rendered benchmark report in `benchmarks/latest-results.md`
- a short benchmark summary in `BENCHMARK_SUMMARY.md`

That still does not make the numbers universal truth. The benchmark is:

- local to one machine and one Python environment
- adapter-based, not official vendor-maintained benchmark code
- workload-equivalent, not feature-equivalent, across libraries
- strongest as a reality check, not as absolute proof of superiority

## Compared Libraries

The comparison below uses at least six well-known Python DI libraries:

- `dependency-injector`: <https://pypi.org/project/dependency-injector/>
- `injector`: <https://pypi.org/project/injector/>
- `lagom`: <https://pypi.org/project/lagom/>
- `punq`: <https://pypi.org/project/punq/>
- `dishka`: <https://pypi.org/project/dishka/>
- `wireup`: <https://pypi.org/project/wireup/>

## Benchmark Snapshot

Command used:

```bash
PYTHONPATH=src .venv/bin/python benchmarks/run_di_benchmarks.py --repeat 5 --iterations 50 --format json > benchmarks/latest-results.json
```

Rendered report:

```bash
python3 benchmarks/render_results_md.py benchmarks/latest-results.json > benchmarks/latest-results.md
```

Versions used in the local `.venv`:

- `dependency-injector 4.49.0`
- `injector 0.24.0`
- `lagom 2.7.7`
- `punq 0.7.0`
- `dishka 1.9.1`
- `wireup 2.9.0`

Adapter note:

- the competitor adapters in [benchmarks/run_di_benchmarks.py](/home/tishka17/src/dixp/benchmarks/run_di_benchmarks.py) were refreshed against the current documented APIs of these installed versions before generating this snapshot, including native collection APIs where available
- the current snapshot also adds composite `start_ready` and `request_cycle` workloads to complement the older microbenchmarks

Measured values below are median latency per operation. Lower is better.

| library | freeze | start | start_ready | validate | singleton_get | scoped_get | collection_all | call | request_cycle |
|---|---|---|---|---|---|---|---|---|---|
| dixp | 37.767 ms | 38.106 ms | 37.895 ms | 39.8 us | 3.6 us | 19.3 us | 14.1 us | 43.7 us | 51.7 us |
| dependency-injector | 57.1 us | 198.8 us | 221.4 us | 22.5 us | 64.2 ns | 568.1 ns | 958.8 ns | 3.2 us | 2.6 us |
| injector | 116.2 us | 55.1 us | 171.1 us | 27.8 us | 1.4 us | 1.3 us | 2.9 us | 40.1 us | 24.5 us |
| lagom | 886.6 ns | 17.4 us | 19.0 us | 1.4 us | 113.0 ns | 426.8 ns | 233.3 ns | 5.7 us | 1.5 us |
| punq | 790.1 ns | 37.2 us | 245.9 us | 162.3 us | 537.4 ns | 13.4 us | 100.8 us | 167.4 us | 170.1 us |
| dishka | 443.1 us | 168.5 us | 1.171 ms | 23.7 us | 284.2 ns | 2.0 us | 486.0 ns | 3.6 us | 3.1 us |
| wireup | 18.9 us | 1.205 ms | 1.239 ms | 2.4 us | 85.6 ns | 1.1 us | 190.4 ns | 1.7 us | 1.8 us |

The benchmark snapshot does not show `dixp` as the raw throughput leader. It does show that:

- `dixp` wins against `punq` on `validate`, `collection_all`, `call`, and `request_cycle`
- `dixp` loses clearly to `dependency-injector`, `injector`, `dishka`, and `wireup` on most measured hot-path metrics
- `lagom` is faster on every measured metric in this snapshot

## What `dixp` Can Honestly Claim Today

Compared with most Python DI containers, `dixp` is unusually strong in these areas:

1. Architecture guardrails, not just object construction.
   `bundle(...)`, exports, private services, `requires(...)`, layer rules, tag rules, incoming/outgoing bundle policies, bundle cycle detection, and graph drift reporting are first-class features.

2. Explainability.
   `doctor()`, `explain()`, bundle graph export, Mermaid output, JSON output, and diffable graph baselines are built in.

3. Typed composition flow.
   `App`, `@service`, `singleton(...)`, `scoped(...)`, `value(...)`, `env(...)`, and named keys keep the public API small and type-oriented.

4. Diagnostics as structured data.
   Errors now carry `code` and `details`, which makes `dixp` easier to integrate with CI, custom reporting, and tests.

5. Explicit runtime ergonomics.
   `get()`, `all()`, `call()`, `warmup()`, `activate()`, `override()`, scopes, sync/async APIs, and validation are exposed as explicit tasks instead of hidden magic.

## Where `dixp` Should Be Careful

These claims should not be made yet:

- "Fastest Python DI container"
- "Faster than `dependency-injector`"
- "Faster than `injector`"
- "Faster than `lagom`"
- "Faster than `dishka`"
- "Faster than `wireup`"
- "Best ecosystem integration"

This is no longer just caution in the abstract. The local benchmark snapshot in this repository does not support those claims. `dependency-injector`, `injector`, `lagom`, `dishka`, and `wireup` are all faster than `dixp` on the measured microbenchmarks and the added composite workloads, and `lagom` leads `dixp` on every metric in this snapshot.

## Head-to-Head Positioning

### 1. `dependency-injector`

Official positioning:
- providers
- overriding
- configuration
- resources

Where `dixp` is better:
- stronger architecture-level controls
- built-in bundle graph reporting and drift detection
- more opinionated, smaller public composition surface
- structured error codes and human-readable graph diagnostics

Where `dependency-injector` is stronger:
- broader ecosystem maturity
- more established provider model
- dramatically stronger raw throughput in this local benchmark snapshot

Speed claim:
- The current local benchmark strongly favors `dependency-injector` on every measured performance metric.

Verdict:
- `dixp` is better for architecture-first teams.
- `dependency-injector` remains much stronger for teams optimizing for raw throughput and mature provider ecosystems.

### 2. `injector`

Official positioning:
- Guice-inspired framework
- modules
- automatic transitive dependency provisioning

Where `dixp` is better:
- better graph diagnostics
- better startup validation story
- better sync/async API split
- better architecture boundary enforcement
- better reporting for CI and review workflows

Where `injector` is stronger:
- familiar mental model for teams that already like Guice-style modules

Speed claim:
- In the current local benchmark, `injector` is faster on every measured metric.

Verdict:
- `dixp` is materially stronger for teams that want operational diagnostics and architecture rules, not just injection.

### 3. `lagom`

Official positioning:
- "just enough" dependency injection
- type-based auto wiring
- strong type focus
- async support

Where `dixp` is better:
- stronger validation and explainability
- stronger architecture constraints
- built-in config loading via typed `env(...)`
- richer runtime report surface

Where `lagom` is stronger:
- lighter "minimum ceremony" positioning
- may feel more natural for teams that want auto-wiring with minimal container surface

Speed claim:
- In the current local benchmark, `lagom` is faster on every measured metric.

Verdict:
- `dixp` is stronger when governance and diagnostics matter more than minimum ceremony.

### 4. `punq`

Official positioning:
- small and simple
- no global state
- no decorators
- easy to understand

Where `dixp` is better:
- scopes
- bundle boundaries
- graph validation
- explainability
- async-aware runtime APIs
- open generic support
- structured diagnostics

Where `punq` is stronger:
- much smaller mental model
- lower adoption cost for tiny projects

Speed claim:
- In the current local benchmark, `punq` is faster on `freeze`, `start`, `start_ready`, `singleton_get`, and `scoped_get`, while `dixp` is faster on `validate`, `collection_all`, `call`, and `request_cycle`.

Verdict:
- `dixp` is materially stronger for medium and large codebases.
- `punq` stays attractive for intentionally tiny setups.

### 5. `dishka`

Official positioning:
- scope-focused DI framework
- agreeable API
- strong scope story

Where `dixp` is better:
- architecture contracts
- bundle graph export and drift detection
- `doctor()` / `explain()` style diagnostics
- structured error reporting

Where `dishka` is stronger:
- scope model is a central design focus
- stronger ecosystem story for framework integrations around scoped execution
- much stronger raw performance in this local benchmark snapshot

Speed claim:
- The current local benchmark favors `dishka` across every measured performance metric.

Verdict:
- this is the closest conceptual competitor for teams that care about runtime correctness.
- `dixp` is stronger on architecture governance; `dishka` is stronger where scopes and integrations are the main concern.

### 6. `wireup`

Official positioning:
- type-driven DI
- fail-fast startup
- framework integrations
- explicit performance positioning

Where `dixp` is better:
- bundle contracts and bundle policy enforcement
- graph explainability
- drift detection and Mermaid/JSON reporting
- smaller conceptual distance between application architecture and container composition

Where `wireup` is stronger:
- stronger public performance story
- broader framework integration story
- clearer "battle-tested" positioning
- much stronger raw performance in this local benchmark snapshot

Speed claim:
- The current local benchmark favors `wireup` across every measured performance metric.

Verdict:
- `dixp` is better for architecture-aware composition and diagnostics.
- `wireup` currently has the stronger explicit performance narrative.

## Practical Summary

If the buyer cares most about:

- architecture safety: `dixp` is one of the strongest options in this set
- human diagnostics: `dixp` is stronger than most of the field
- typed app composition with a small public API: `dixp` is strong
- raw performance: `dependency-injector`, `injector`, `lagom`, `dishka`, and `wireup` are stronger in this local snapshot
- scope-centered framework integration: `dishka` is a serious competitor
- minimalism: `punq` and `lagom` remain attractive

Short version:

- `dixp` is clearly better than `injector` and `punq` for architecture-first teams.
- `dixp` is usually better than `lagom` when explainability and policy enforcement matter.
- `dixp` competes on safety, diagnostics, and architecture controls, not on raw throughput speed.
- `dixp` should not claim it is faster than `dependency-injector`, `injector`, `lagom`, `dishka`, or `wireup` under the current benchmark snapshot.

## What "Faster" Should Mean for `dixp`

The repository now includes a reproducible local harness for this work:

```bash
PYTHONPATH=src .venv/bin/python benchmarks/run_di_benchmarks.py
```

The current snapshot is more useful now that it includes composite `start_ready` and `request_cycle` scenarios, but it is still not complete. A stronger benchmark story should still measure at least:

1. Cold graph compile / freeze time on a denser application graph.
2. `start(validate=True)` and explicit warmup cost under more realistic graph size.
3. Async request-path cost (`acall()` / async scopes / async resources).
4. Concurrency under parallel request scopes.
5. Failure-path quality:
   missing dependency, circular dependency, lifetime mismatch, bundle policy violation.

The current snapshot already suggests that `dixp` is unlikely to win every microbenchmark or composite runtime benchmark. Its strongest story is:

- better safety per line of composition
- better diagnostics per failure
- better architecture control per container

That is a valuable position, but it is different from "highest raw resolve throughput".

## Recommended Marketing Language

Safe claims:

- "`dixp` is a typed Python IoC toolkit that combines DI with architecture validation."
- "`dixp` gives teams built-in graph diagnostics, bundle contracts, and drift detection."
- "`dixp` favors explicit composition and operational clarity over magical wiring."
- "`dixp` optimizes for architecture safety and diagnostics more than raw container throughput."

Unsafe claims under the current benchmark snapshot:

- "`dixp` is the fastest Python DI container."
- "`dixp` beats `dependency-injector` on throughput."
- "`dixp` beats `injector` on throughput."
- "`dixp` beats `lagom` on throughput."
- "`dixp` beats `dishka` on throughput."
- "`dixp` beats `wireup` on request-time injection performance."

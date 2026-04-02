# Benchmarks

This directory contains a reproducible local benchmark harness for `dixp`
and adapter-based comparisons with competing Python DI libraries.

Goals:

- measure `dixp` on realistic container workloads
- keep output machine-readable
- avoid fake competitive claims when other libraries are not installed

## Run

From the repository root:

```bash
PYTHONPATH=src .venv/bin/python benchmarks/run_di_benchmarks.py
```

The harness includes adapters for:

- `dixp`
- `dependency-injector`
- `injector`
- `lagom`
- `punq`
- `dishka`
- `wireup`

If a competitor package is not installed, it is reported as `skipped`.
If a package is installed but its API differs from the adapter assumptions, the harness reports an adapter failure instead of crashing the whole run.

## Workloads

The harness measures these scenarios:

1. `freeze`
   Compile the app graph into a blueprint.
2. `start`
   Build a runtime container from the compiled app.
3. `validate`
   Validate the compiled graph.
4. `singleton_get`
   Repeated hot resolution of a singleton service.
5. `scoped_get`
   Repeated hot resolution of a scoped service inside an active scope.
6. `collection_all`
   Repeated resolution of a multi-binding collection.
7. `call`
   Repeated dependency-injected callable invocation.

## Output

Default output is a human-readable table. JSON is also available:

```bash
PYTHONPATH=src .venv/bin/python benchmarks/run_di_benchmarks.py --format json
```

A typical checked-in update flow is:

```bash
PYTHONPATH=src .venv/bin/python benchmarks/run_di_benchmarks.py --repeat 5 --iterations 50 --format json > benchmarks/latest-results.json
python3 benchmarks/render_results_md.py benchmarks/latest-results.json > benchmarks/latest-results.md
```

To render a checked-in markdown report from a saved JSON snapshot:

```bash
python3 benchmarks/render_results_md.py benchmarks/latest-results.json > benchmarks/latest-results.md
```

Related repository docs:

- [../README.md](/home/tishka17/src/dixp/README.md)
- [../BENCHMARK_SUMMARY.md](/home/tishka17/src/dixp/BENCHMARK_SUMMARY.md)
- [../COMPETITIVE_COMPARISON.md](/home/tishka17/src/dixp/COMPETITIVE_COMPARISON.md)

## Competitive Use

If you want to compare `dixp` against other DI libraries, use the same workload shape:

- identical object graph depth
- identical number of collection contributors
- identical benchmark loop sizes
- warm the container before hot-path measurements
- separate compile/start costs from hot resolve throughput

Do not publish head-to-head claims until the competing dependency is installed and the adapter has been validated against the exact library version used in the benchmark environment.

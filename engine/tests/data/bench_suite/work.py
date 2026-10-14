"""The tracer benchmark's workloads (E01): A08's two (spikes/A08/tracer_bench.py), sized so
that the steady state dominates, and many small functions."""


def fib(n):
    return n if n < 2 else fib(n - 1) + fib(n - 2)


def normalise_record(record):
    name = record["name"].strip().lower()
    tags = sorted(set(record["tags"]))
    return {"name": name, "tags": tags, "total": sum(record["values"])}


RECORDS = [
    {"name": f" Item{i} ", "tags": ["b", "a", "b"], "values": list(range(i % 7))}
    for i in range(40_000)
]


def _small(k):
    def small(x):
        return x * k + 1

    return small


SMALL = [_small(k) for k in range(20)]

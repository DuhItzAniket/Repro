"""Functions the tracer's tests call: one per kind of call it records."""

import threading


def add(a, b):
    return a + b


def fails(x):
    raise ValueError("bad", x)


def gen(n):
    for i in range(n):
        yield i * 2


def recurse(n):
    return 0 if n == 0 else 1 + recurse(n - 1)


def with_kw(a, *args, b=2, **kw):
    return (a, args, b, kw)


def many(n):
    return sum(add(i, 1) for i in range(n))


def threaded(count):
    results = []
    workers = [threading.Thread(target=lambda i=i: results.append(add(i, i))) for i in range(count)]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join()
    return sorted(results)


class Box:
    def __init__(self, value):
        self.value = value

    def size(self):
        return len(self.value)

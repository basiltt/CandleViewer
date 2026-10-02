"""THROWAWAY: canonicalise+hash a 100-node document, 1000 iterations; prints p50/p99 (ms)."""
from __future__ import annotations

import json
import statistics
import time

import canon


def big_doc() -> object:
    kids = [{"node_id": f"c{i}", "type": "compare", "op": ">",
             "left": {"metric": "price"}, "right": {"const": f"{i}.250"}} for i in range(98)]
    return canon.parse_ir(json.dumps({"node_id": "root", "type": "all_of", "children": kids,
                                      "presentation": {"graph_layout": {}}}))


def main() -> None:
    doc = big_doc()
    for name in canon.STRATEGIES:
        samples = []
        for _ in range(1000):
            t = time.perf_counter()
            canon.ir_hash(doc, name)
            samples.append((time.perf_counter() - t) * 1000)
        samples.sort()
        print(f"{name}: p50={statistics.median(samples):.3f}ms p99={samples[989]:.3f}ms")


if __name__ == "__main__":
    main()

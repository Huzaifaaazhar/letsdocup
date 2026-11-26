"""Batch-level container comparison (CONSOL detection).

Runs over EVERY document in the batch, every time. A container shared by
two or more DIFFERENT BL numbers makes every one of those BLs CONSOL.
Comparison is exact on the normalised container number (only spaces and
hyphens removed, upper-cased). Similar-looking numbers are NEVER merged;
they are only reported as a warning so the user can check for misreads.
"""
from __future__ import annotations

from collections import defaultdict


def compare_containers(docs: list[dict]) -> dict:
    """docs: [{"doc_key", "bl_number", "containers": [{"container": ...}]}]

    Returns {
      "per_doc": {doc_key: [{"container", "shared_with": [bl, ...]}]},
      "groups": [{"bls": [...], "containers": [...]}],
      "unidentified_links": {doc_key: [{"container", "unidentified_docs": [...]}]},
      "near_matches": [...],
      "stats": {...},
    }
    """
    index: dict[str, set[str]] = defaultdict(set)          # container -> BL numbers
    unident: dict[str, set[str]] = defaultdict(set)        # container -> unidentified doc keys
    bl_containers: dict[str, set[str]] = defaultdict(set)
    total_refs = 0
    for d in docs:
        conts = {c["container"] for c in d.get("containers") or []}
        total_refs += len(conts)
        for c in conts:
            if d.get("bl_number"):
                index[c].add(d["bl_number"])
                bl_containers[d["bl_number"]].add(c)
            else:
                unident[c].add(d["doc_key"])

    shared = {c: bls for c, bls in index.items() if len(bls) >= 2}

    per_doc: dict[str, list[dict]] = {}
    for d in docs:
        bl = d.get("bl_number")
        if not bl:
            continue
        links = []
        for c in sorted(bl_containers.get(bl, ())):
            if c in shared:
                links.append({"container": c, "shared_with": sorted(shared[c] - {bl})})
        if links:
            per_doc[d["doc_key"]] = links

    # Connected groups of BLs (A-B share X, B-C share Y => A,B,C one group)
    parent: dict[str, str] = {}

    def find(x):
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for c, bls in shared.items():
        bls = sorted(bls)
        for b in bls[1:]:
            parent[find(b)] = find(bls[0])
    grp: dict[str, dict] = {}
    for c, bls in shared.items():
        root = find(next(iter(bls)))
        g = grp.setdefault(root, {"bls": set(), "containers": set()})
        g["bls"] |= bls
        g["containers"].add(c)
    groups = sorted(
        ({"bls": sorted(g["bls"]), "containers": sorted(g["containers"])} for g in grp.values()),
        key=lambda g: g["bls"][0],
    )
    for i, g in enumerate(groups, start=1):
        g["group_id"] = i

    # Containers that also appear on pages without a readable BL number.
    unidentified_links: dict[str, list[dict]] = {}
    for d in docs:
        bl = d.get("bl_number")
        if not bl:
            continue
        for c in sorted(bl_containers.get(bl, ())):
            if c in unident:
                unidentified_links.setdefault(d["doc_key"], []).append(
                    {"container": c, "unidentified_docs": sorted(unident[c])}
                )

    # Near matches (one character different, same length) between different BLs.
    near = []
    conts = sorted(index)
    by_len: dict[int, list[str]] = defaultdict(list)
    for c in conts:
        by_len[len(c)].append(c)
    for L, items in by_len.items():
        if len(items) > 3000:      # keep this cheap on huge batches
            continue
        for i, a in enumerate(items):
            for b in items[i + 1:]:
                if sum(x != y for x, y in zip(a, b)) == 1 and index[a] != index[b]:
                    near.append({"a": a, "a_bls": sorted(index[a]), "b": b, "b_bls": sorted(index[b])})

    return {
        "per_doc": per_doc,
        "groups": groups,
        "unidentified_links": unidentified_links,
        "near_matches": near,
        "stats": {
            "documents_compared": len(docs),
            "bls_with_containers": len(bl_containers),
            "unique_containers": len(index),
            "container_references": total_refs,
            "shared_containers": len(shared),
            "consol_bls": len(per_doc),
            "groups": len(groups),
        },
    }

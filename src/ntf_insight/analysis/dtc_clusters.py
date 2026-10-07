"""Descriptive DTC co-occurrence clusters.

These clusters are intentionally deterministic and explainable. They describe DTCs that
occur in the same cases; they are not an ML/root-cause classification.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from itertools import combinations

from ntf_insight.domain.case import NTFCase

FaultKey = tuple[str, str]


@dataclass(frozen=True, slots=True)
class DTCNode:
    key: FaultKey
    case_count: int
    event_count: int
    case_ids: tuple[str, ...]

    @property
    def ecu(self) -> str:
        return self.key[0]

    @property
    def dtc_code(self) -> str:
        return self.key[1]


@dataclass(frozen=True, slots=True)
class DTCEdge:
    left: FaultKey
    right: FaultKey
    case_count: int
    case_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class DTCCluster:
    cluster_id: int
    faults: tuple[FaultKey, ...]
    case_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class DTCNetwork:
    nodes: tuple[DTCNode, ...]
    edges: tuple[DTCEdge, ...]
    clusters: tuple[DTCCluster, ...]

    def cluster_by_fault(self) -> dict[FaultKey, int]:
        return {
            fault: cluster.cluster_id
            for cluster in self.clusters
            for fault in cluster.faults
        }


def build_dtc_network(cases: list[NTFCase]) -> DTCNetwork:
    """Build a DTC co-occurrence network from normalized cases."""
    node_cases: dict[FaultKey, set[str]] = defaultdict(set)
    event_counts: Counter[FaultKey] = Counter()
    edge_cases: dict[tuple[FaultKey, FaultKey], set[str]] = defaultdict(set)

    for case in cases:
        case_faults = {event.fault_key for event in case.diagnostics}
        for event in case.diagnostics:
            event_counts[event.fault_key] += 1
            node_cases[event.fault_key].add(case.case_id)

        for left, right in combinations(sorted(case_faults), 2):
            edge_cases[(left, right)].add(case.case_id)

    nodes = tuple(
        sorted(
            (
                DTCNode(
                    key=key,
                    case_count=len(case_ids),
                    event_count=event_counts[key],
                    case_ids=tuple(sorted(case_ids)),
                )
                for key, case_ids in node_cases.items()
            ),
            key=lambda item: (-item.case_count, -item.event_count, item.key),
        )
    )

    edges = tuple(
        sorted(
            (
                DTCEdge(
                    left=left,
                    right=right,
                    case_count=len(case_ids),
                    case_ids=tuple(sorted(case_ids)),
                )
                for (left, right), case_ids in edge_cases.items()
            ),
            key=lambda item: (-item.case_count, item.left, item.right),
        )
    )

    adjacency: dict[FaultKey, set[FaultKey]] = {
        node.key: set() for node in nodes
    }
    for edge in edges:
        adjacency[edge.left].add(edge.right)
        adjacency[edge.right].add(edge.left)

    components: list[tuple[tuple[FaultKey, ...], tuple[str, ...]]] = []
    unseen = set(adjacency)
    while unseen:
        start = min(unseen)
        stack = [start]
        faults: set[FaultKey] = set()
        component_cases: set[str] = set()

        while stack:
            current = stack.pop()
            if current in faults:
                continue
            faults.add(current)
            unseen.discard(current)
            component_cases.update(node_cases[current])
            stack.extend(sorted(adjacency[current] - faults, reverse=True))

        components.append(
            (tuple(sorted(faults)), tuple(sorted(component_cases)))
        )

    components.sort(
        key=lambda item: (-len(item[1]), -len(item[0]), item[0])
    )
    clusters = tuple(
        DTCCluster(
            cluster_id=index,
            faults=faults,
            case_ids=case_ids,
        )
        for index, (faults, case_ids) in enumerate(components, start=1)
    )

    return DTCNetwork(nodes=nodes, edges=edges, clusters=clusters)

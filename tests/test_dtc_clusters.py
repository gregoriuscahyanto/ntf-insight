from ntf_insight.analysis.dtc_clusters import build_dtc_network
from ntf_insight.demo.synthetic_cases import build_demo_cases


def test_dtc_network_contains_nodes_edges_and_clusters() -> None:
    network = build_dtc_network(build_demo_cases())

    assert network.nodes
    assert network.clusters
    assert any(node.key == ("CPC3", "P26F100") for node in network.nodes)
    assert all(cluster.cluster_id >= 1 for cluster in network.clusters)


def test_dtc_edges_are_traceable_to_cases() -> None:
    network = build_dtc_network(build_demo_cases())

    assert all(edge.case_count == len(edge.case_ids) for edge in network.edges)
    assert all(edge.case_count >= 1 for edge in network.edges)

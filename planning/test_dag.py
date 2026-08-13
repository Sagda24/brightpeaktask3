import pytest

from planning.dag import DAG, Node, DAGCycleError


def make_dag():
    return DAG(request={"student_id": 1, "free_text": "test"}, method="decomposition_first")


def test_topological_order_respects_dependencies():
    dag = make_dag()
    dag.add_node(Node(task_id="a", instruction="x", tool="get_profile", depends_on=[]))
    dag.add_node(Node(task_id="b", instruction="y", tool="check_prerequisites", depends_on=["a"]))
    dag.add_node(Node(task_id="c", instruction="z", tool="enroll", depends_on=["b"]))
    order = dag.topological_order()
    assert order.index("a") < order.index("b") < order.index("c")


def test_duplicate_task_id_rejected():
    dag = make_dag()
    dag.add_node(Node(task_id="a", instruction="x", tool="get_profile", depends_on=[]))
    with pytest.raises(ValueError):
        dag.add_node(Node(task_id="a", instruction="dup", tool="get_profile", depends_on=[]))


def test_unknown_dependency_rejected():
    dag = make_dag()
    with pytest.raises(ValueError):
        dag.add_node(Node(task_id="a", instruction="x", tool="get_profile", depends_on=["ghost"]))


def test_cycle_rejected_at_construction_time():
    dag = make_dag()
    dag.add_node(Node(task_id="a", instruction="x", tool="get_profile", depends_on=[]))
    dag.add_node(Node(task_id="b", instruction="y", tool="get_profile", depends_on=["a"]))
    # force a cycle a -> b -> a directly on the stored node, then verify
    # the DAG's own topological_order (the same check add_node relies
    # on) catches it.
    dag.nodes["a"].depends_on.append("b")
    with pytest.raises(DAGCycleError):
        dag.topological_order()


def test_add_edge_rejects_cycle_and_rolls_back():
    dag = make_dag()
    dag.add_node(Node(task_id="a", instruction="x", tool="get_profile", depends_on=[]))
    dag.add_node(Node(task_id="b", instruction="y", tool="get_profile", depends_on=["a"]))
    with pytest.raises(DAGCycleError):
        dag.add_edge(from_task="b", to_task="a")  # would create a<->b cycle
    # rollback must have happened: b must not depend on a-and-a-on-b
    assert "b" not in dag.nodes["a"].depends_on

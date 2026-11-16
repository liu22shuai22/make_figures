"""Read-only review of an E-R model."""
from typing import Annotated, Literal, TypedDict

from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field, StringConstraints

class Finding(BaseModel):
    message: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=240)]
    kind: Literal["entity", "relation", "model"]
    index: Annotated[int, Field(strict=True, ge=0)] | None = None


class State(TypedDict, total=False):
    spec: dict
    structural: list[Finding]


def check_structure(state: State) -> dict:
    relations = state["spec"]["relations"]
    seen = set()
    findings = []
    for index, relation in enumerate(relations):
        ends = tuple(sorted(zip(relation["entities"], relation["card"])))
        signature = relation["name"], ends, tuple(sorted(relation["attrs"]))
        if signature in seen:
            findings.append(Finding(kind="relation", index=index,
                                    message=f"联系「{relation['name']}」与前面一条同名联系的端点、基数和属性完全相同。"))
        seen.add(signature)
    return {"structural": findings}


graph = (StateGraph(State).add_node("check_structure", check_structure)
         .add_edge(START, "check_structure").add_edge("check_structure", END).compile())


def review_model(spec: dict) -> dict:
    result = graph.invoke({"spec": spec})
    return {"structural": result["structural"], "status": "local"}

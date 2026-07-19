"""只读盘点应用层 completion 出口及统一账本接入状态。"""

from __future__ import annotations

import argparse
import ast
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


DEFAULT_SOURCE_ROOT = Path(__file__).resolve().parents[1]

_KNOWN_UNIFIED_OUTLET_IDENTITIES = frozenset(
    {
        "services/chapter_plan_llm.py::ChapterPlanService._run_structured_task::accounted_call",
        "services/literary_eval.py::LLMLiteraryCaseGenerator.__call__::accounted_call",
        "services/llm_accounting.py::_AccountedCompletionProbeExecution.generate_accounted::accounted_probe_transport",
        "services/llm_accounting.py::execute_accounted_completion_probe::accounted_call",
        "services/llm_task_runner.py::LLMNodeRunner.run::accounted_call",
        "services/llm_task_runner.py::LLMNodeRunner.run_task::accounted_call",
        "services/snowflake_workspace_llm.py::SnowflakeWorkspaceLLMService._run_structured_task::accounted_call",
        "services/style_reference/_llm_helper.py::call_llm_node::accounted_call",
        "services/style_reference/segmentation/llm.py::_classify_via_node::accounted_call",
    }
)


def _attribute_name(node: ast.AST | None) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        prefix = _attribute_name(node.value)
        return f"{prefix}.{node.attr}" if prefix else node.attr
    if isinstance(node, ast.Call):
        return _attribute_name(node.func)
    return None


_SAFE_NON_COMPLETION_GENERATE_REFERENCES = frozenset(
    {
        (
            "services/llm_client.py",
            "LLMClient.generate_accounted",
            "self",
        ),
        (
            "services/scene_blueprint.py",
            "SceneBlueprintService.ensure_for_scene",
            "self",
        ),
        (
            "services/scene_execution.py",
            "SceneExecutionContractService.get_or_create",
            "self",
        ),
        (
            "api/routes/projects.py",
            "generate_outline_plan",
            "OutlinePlannerService",
        ),
        (
            "api/routes/scenes.py",
            "generate_scene_execution_contract",
            "SceneExecutionContractService",
        ),
        (
            "api/routes/scenes.py",
            "generate_scene_literary_blueprint",
            "SceneBlueprintService",
        ),
        (
            "api/routes/snowflake.py",
            "generate_snowflake_step",
            "SnowflakePlannerService",
        ),
        (
            "api/routes/style_reference.py",
            "preview_profile._do",
            "svc",
        ),
    }
)


@dataclass(slots=True)
class _Frame:
    accounted_call_aliases: set[str] = field(default_factory=set)
    accounting_module_aliases: set[str] = field(default_factory=set)
    httpx_module_aliases: set[str] = field(default_factory=set)
    httpx_post_aliases: set[str] = field(default_factory=set)
    httpx_client_aliases: set[str] = field(default_factory=set)
    http_client_names: set[str] = field(default_factory=set)


class _OutletVisitor(ast.NodeVisitor):
    def __init__(
        self,
        *,
        path: Path,
        root: Path,
        source: str,
    ) -> None:
        self.path = path
        self.root = root
        self.source = source
        self.outlets: list[dict[str, Any]] = []
        self.classes: list[ast.ClassDef] = []
        self.functions: list[ast.FunctionDef | ast.AsyncFunctionDef] = []
        self.frames: list[_Frame] = [_Frame()]

    @property
    def frame(self) -> _Frame:
        return self.frames[-1]

    @property
    def relative_path(self) -> str:
        return self.path.relative_to(self.root).as_posix()

    @property
    def qualname(self) -> str:
        parts = [node.name for node in self.classes]
        parts.extend(node.name for node in self.functions)
        return ".".join(parts) or "<module>"

    def visit_ClassDef(self, node: ast.ClassDef) -> None:  # noqa: N802
        self.classes.append(node)
        self.frames.append(_Frame())
        self.generic_visit(node)
        self.frames.pop()
        self.classes.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:  # noqa: N802
        self._visit_function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:  # noqa: N802
        self._visit_function(node)

    def _visit_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        http_client_names = {
            argument.arg
            for argument in [
                *node.args.posonlyargs,
                *node.args.args,
                *node.args.kwonlyargs,
            ]
            if self._is_http_client_type(_attribute_name(argument.annotation))
        }
        self.functions.append(node)
        self.frames.append(_Frame(http_client_names=http_client_names))
        self.generic_visit(node)
        self.frames.pop()
        self.functions.pop()

    def visit_Import(self, node: ast.Import) -> None:  # noqa: N802
        for alias in node.names:
            bound_name = alias.asname or alias.name
            if alias.name == "httpx":
                self.frame.httpx_module_aliases.add(bound_name)
            elif alias.name == "novel_system.services.llm_accounting":
                self.frame.accounting_module_aliases.add(bound_name)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:  # noqa: N802
        for alias in node.names:
            bound_name = alias.asname or alias.name
            if node.module == "httpx":
                if alias.name == "post":
                    self.frame.httpx_post_aliases.add(bound_name)
                elif alias.name in {"Client", "AsyncClient"}:
                    self.frame.httpx_client_aliases.add(bound_name)
            elif node.module == "novel_system.services.llm_accounting":
                if alias.name == "execute_accounted_call":
                    self.frame.accounted_call_aliases.add(bound_name)
            elif node.module == "novel_system.services" and alias.name == "llm_accounting":
                self.frame.accounting_module_aliases.add(bound_name)

    def visit_Assign(self, node: ast.Assign) -> None:  # noqa: N802
        self._record_assignment(node.targets, node.value)
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:  # noqa: N802
        self._record_assignment([node.target], node.value, annotation=node.annotation)
        self.generic_visit(node)

    def _record_assignment(
        self,
        targets: list[ast.expr],
        value: ast.AST | None,
        *,
        annotation: ast.AST | None = None,
    ) -> None:
        names = [target.id for target in targets if isinstance(target, ast.Name)]
        if not names:
            return
        if self._is_http_client_constructor(value):
            self.frame.http_client_names.update(names)
        elif isinstance(value, ast.Name) and self._visible_in_frames(
            value.id, "http_client_names"
        ):
            self.frame.http_client_names.update(names)
        if self._is_http_client_type(_attribute_name(annotation)):
            self.frame.http_client_names.update(names)

    def visit_With(self, node: ast.With) -> None:  # noqa: N802
        self._record_context_managers(node.items)
        self.generic_visit(node)

    def visit_AsyncWith(self, node: ast.AsyncWith) -> None:  # noqa: N802
        self._record_context_managers(node.items)
        self.generic_visit(node)

    def _record_context_managers(self, items: list[ast.withitem]) -> None:
        for item in items:
            if (
                self._is_http_client_constructor(item.context_expr)
                and isinstance(item.optional_vars, ast.Name)
            ):
                self.frame.http_client_names.add(item.optional_vars.id)

    def visit_Call(self, node: ast.Call) -> None:  # noqa: N802
        if self._is_accounted_call(node.func):
            self._append(node, kind="accounted_call", unified=True)
        elif isinstance(node.func, ast.Name) and self._visible_in_frames(
            node.func.id, "httpx_post_aliases"
        ):
            self._append(node, kind="completion_probe_httpx_post", unified=False)
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:  # noqa: N802
        if node.attr == "generate":
            if not self._is_exact_safe_generate_reference(node):
                self._append(node, kind="direct_generate", unified=False)
        elif node.attr == "post" and self._is_http_post_attribute(node):
            if self._is_accounted_probe_transport(node):
                self._append(node, kind="accounted_probe_transport", unified=True)
            elif not self._is_exact_provider_transport(node):
                self._append(node, kind="completion_probe_httpx_post", unified=False)
        self.generic_visit(node)

    def _visible_in_frames(self, name: str, field_name: str) -> bool:
        return any(name in getattr(frame, field_name) for frame in reversed(self.frames))

    def _is_accounted_call(self, node: ast.AST) -> bool:
        if isinstance(node, ast.Name):
            if self._visible_in_frames(node.id, "accounted_call_aliases"):
                return True
            return (
                node.id == "execute_accounted_call"
                and self.relative_path == "services/llm_accounting.py"
                and self.qualname == "execute_accounted_completion_probe"
            )
        if not isinstance(node, ast.Attribute) or node.attr != "execute_accounted_call":
            return False
        module_name = _attribute_name(node.value)
        return bool(
            module_name
            and self._visible_in_frames(module_name, "accounting_module_aliases")
        )

    def _is_http_client_type(self, name: str | None) -> bool:
        if name is None:
            return False
        if self._visible_in_frames(name, "httpx_client_aliases"):
            return True
        return any(
            name == f"{alias}.{client_type}"
            for frame in self.frames
            for alias in frame.httpx_module_aliases
            for client_type in ("Client", "AsyncClient")
        )

    def _is_http_client_constructor(self, node: ast.AST | None) -> bool:
        if not isinstance(node, ast.Call):
            return False
        name = _attribute_name(node.func)
        if name and self._visible_in_frames(name, "httpx_client_aliases"):
            return True
        return any(
            name == f"{alias}.{client}"
            for frame in self.frames
            for alias in frame.httpx_module_aliases
            for client in ("Client", "AsyncClient")
        )

    def _is_http_client_expression(self, node: ast.AST | None) -> bool:
        if self._is_http_client_constructor(node):
            return True
        return (
            isinstance(node, ast.Name)
            and self._visible_in_frames(node.id, "http_client_names")
        )

    def _is_http_post_attribute(self, node: ast.Attribute) -> bool:
        module_name = _attribute_name(node.value)
        if module_name and self._visible_in_frames(module_name, "httpx_module_aliases"):
            return True
        return self._is_http_client_expression(node.value)

    def _is_exact_safe_generate_reference(self, node: ast.Attribute) -> bool:
        return (
            self.relative_path,
            self.qualname,
            _attribute_name(node.value),
        ) in _SAFE_NON_COMPLETION_GENERATE_REFERENCES

    def _is_accounted_probe_transport(self, node: ast.Attribute) -> bool:
        return (
            self.relative_path == "services/llm_accounting.py"
            and self.qualname == "_AccountedCompletionProbeExecution.generate_accounted"
            and _attribute_name(node.value) == "httpx"
        )

    def _is_exact_provider_transport(self, node: ast.Attribute) -> bool:
        """排除账本下游的已知 provider 传输层，不使用名称模糊匹配。"""

        return (
            self.relative_path == "services/llm_client.py"
            and self.qualname == "LLMClient._generate_once"
            and _attribute_name(node.value) == "client"
        )

    def _append(self, node: ast.AST, *, kind: str, unified: bool) -> None:
        identity = f"{self.relative_path}::{self.qualname}::{kind}"
        unified = unified and identity in _KNOWN_UNIFIED_OUTLET_IDENTITIES
        self.outlets.append(
            {
                "identity": identity,
                "path": self.relative_path,
                "qualname": self.qualname,
                "line": node.lineno,
                "kind": kind,
                "expression": ast.get_source_segment(self.source, node) or "<unknown>",
                "unified": unified,
            }
        )


def inventory_report(source_root: Path | str = DEFAULT_SOURCE_ROOT) -> dict[str, Any]:
    """返回可直接 JSON 序列化的只读出口清单。"""

    root = Path(source_root).resolve()
    outlets: list[dict[str, Any]] = []
    for path in sorted(root.rglob("*.py")):
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
        visitor = _OutletVisitor(
            path=path,
            root=root,
            source=source,
        )
        visitor.visit(tree)
        outlets.extend(visitor.outlets)
    outlets.sort(key=lambda item: (item["identity"], item["line"]))
    identity_counts = {
        identity: sum(1 for item in outlets if item["identity"] == identity)
        for identity in {item["identity"] for item in outlets}
    }
    for item in outlets:
        if item["unified"] and identity_counts[item["identity"]] != 1:
            item["unified"] = False
    unified = sum(1 for item in outlets if item["unified"])
    return {
        "schema": "llm-outlet-inventory-v1",
        "source_root": str(root),
        "summary": {
            "application_outlets": len(outlets),
            "unified": unified,
            "unaccounted": len(outlets) - unified,
        },
        "outlets": outlets,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, default=DEFAULT_SOURCE_ROOT)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--json", action="store_true", help="兼容证据命令；输出始终为 JSON")
    args = parser.parse_args(argv)
    report = inventory_report(args.source_root)
    payload = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload + "\n", encoding="utf-8")
    else:
        print(payload)
    identities = {item["identity"] for item in report["outlets"]}
    identity_gate_ok = (
        len(report["outlets"]) == len(_KNOWN_UNIFIED_OUTLET_IDENTITIES)
        and identities == _KNOWN_UNIFIED_OUTLET_IDENTITIES
    )
    return 1 if report["summary"]["unaccounted"] or not identity_gate_ok else 0


if __name__ == "__main__":
    raise SystemExit(main())

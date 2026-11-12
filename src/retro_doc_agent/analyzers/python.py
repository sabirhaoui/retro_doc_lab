"""Extraction d'imports, fonctions et appels via l'AST Python."""

from __future__ import annotations

import ast
import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from retro_doc_agent.models.architecture import (
    CallEdge,
    FunctionFact,
    ImportEdge,
    ModuleFact,
    PythonAnalysis,
    SecretSignal,
)
from retro_doc_agent.models.report import EvidenceRef
from retro_doc_agent.scanner.filesystem import FileRecord, ScannedText

BRANCH_NODES = (
    ast.If,
    ast.IfExp,
    ast.For,
    ast.AsyncFor,
    ast.While,
    ast.Try,
    ast.ExceptHandler,
    ast.BoolOp,
)
SECRET_NAME = re.compile(
    r"(?:secret|password|passwd|token|api[_-]?key|private[_-]?key|credential)",
    re.I,
)
HTTP_DECORATORS = {"delete", "get", "patch", "post", "put", "route"}
WORKER_DECORATORS = {"receiver", "scheduled_job", "task"}


@dataclass(frozen=True)
class _ImportObservation:
    source_path: str
    source_module: str
    requested_module: str
    imported_member: str | None
    local_name: str
    alias_module: str
    line: int


@dataclass(frozen=True)
class _CallObservation:
    caller: str
    module: str
    class_name: str | None
    expression: str
    line: int
    path: str


class PythonAnalyzer:
    """Analyse les fichiers Python sans imports ni exécution du projet observé."""

    def __init__(self) -> None:
        self._modules: list[ModuleFact] = []
        self._imports: list[_ImportObservation] = []
        self._functions: list[FunctionFact] = []
        self._calls: list[_CallObservation] = []
        self._secret_signals: list[SecretSignal] = []
        self._unparsed_files: list[str] = []
        self._records: dict[str, FileRecord] = {}

    def supports(self, path: Path) -> bool:
        return path.suffix.casefold() == ".py"

    def observe(self, source_file: ScannedText) -> None:
        if not self.supports(Path(source_file.record.path)):
            return
        self._records[source_file.record.path] = source_file.record
        module_name = _module_name(source_file.record.path)
        try:
            tree = ast.parse(source_file.text, filename=source_file.record.path)
        except SyntaxError:
            self._unparsed_files.append(source_file.record.path)
            return
        module_evidence = (
            _evidence(source_file.record, 1, source_file.record.line_count),
        ) if source_file.record.line_count else ()
        self._modules.append(
            ModuleFact(
                name=module_name,
                path=source_file.record.path,
                line_count=source_file.record.line_count,
                evidence=module_evidence,
            )
        )
        collector = _PythonCollector(source_file.record, module_name)
        collector.visit(tree)
        self._imports.extend(collector.imports)
        self._functions.extend(collector.functions)
        self._calls.extend(collector.calls)
        self._secret_signals.extend(collector.secret_signals)

    def result(self) -> PythonAnalysis:
        modules = tuple(sorted(self._modules, key=lambda item: item.path))
        module_paths: dict[str, list[str]] = defaultdict(list)
        for module in modules:
            module_paths[module.name].append(module.path)
        functions_by_name: dict[str, list[FunctionFact]] = defaultdict(list)
        functions_by_module: dict[str, list[FunctionFact]] = defaultdict(list)
        for function in self._functions:
            functions_by_name[function.name].append(function)
            functions_by_module[function.module].append(function)

        imports: list[ImportEdge] = []
        aliases_by_path: dict[str, dict[str, tuple[str, str | None]]] = defaultdict(dict)
        for import_observation in self._imports:
            candidate_names = [import_observation.requested_module]
            if import_observation.imported_member:
                candidate_names.insert(
                    0,
                    f"{import_observation.requested_module}.{import_observation.imported_member}",
                )
            target_name = next(
                (name for name in candidate_names if len(module_paths.get(name, [])) == 1),
                None,
            )
            alias_module = (
                import_observation.alias_module
                if import_observation.imported_member is None
                else target_name or import_observation.requested_module
            )
            alias_member = (
                import_observation.imported_member if target_name is None else None
            )
            aliases_by_path[import_observation.source_path][import_observation.local_name] = (
                alias_module,
                alias_member,
            )
            if target_name is not None:
                target_path = module_paths[target_name][0]
                imports.append(
                    ImportEdge(
                        source=import_observation.source_path,
                        target=target_path,
                        evidence=_evidence(
                            self._record_for_path(import_observation.source_path),
                            import_observation.line,
                        ),
                    )
                )

        calls: list[CallEdge] = []
        for call_observation in self._calls:
            target_name = self._resolve_call(
                call_observation,
                aliases_by_path.get(call_observation.path, {}),
                functions_by_name,
                functions_by_module,
            )
            calls.append(
                CallEdge(
                    caller=call_observation.caller,
                    callee_expression=call_observation.expression,
                    target=target_name,
                    evidence=_evidence(
                        self._record_for_path(call_observation.path),
                        call_observation.line,
                    ),
                )
            )
        return PythonAnalysis(
            modules=modules,
            imports=tuple(
                sorted(
                    imports,
                    key=lambda item: (item.source, item.target, item.evidence.start_line),
                )
            ),
            functions=tuple(
                sorted(self._functions, key=lambda item: (item.path, item.start_line))
            ),
            calls=tuple(
                sorted(
                    calls,
                    key=lambda item: (
                        item.caller,
                        item.evidence.path,
                        item.evidence.start_line,
                    ),
                )
            ),
            entrypoints=tuple(
                item for item in self._functions if item.entrypoint_kind is not None
            ),
            secret_signals=tuple(
                sorted(
                    self._secret_signals,
                    key=lambda item: (item.evidence.path, item.evidence.start_line),
                )
            ),
            unparsed_files=tuple(sorted(self._unparsed_files)),
            limitations=(
                "Les appels dynamiques, réflexion, décorateurs opaques et injections "
                "ne sont pas résolus.",
            ),
        )

    def _record_for_path(self, path: str) -> FileRecord:
        return self._records[path]

    @staticmethod
    def _resolve_call(
        observation: _CallObservation,
        aliases: dict[str, tuple[str, str | None]],
        functions_by_name: dict[str, list[FunctionFact]],
        functions_by_module: dict[str, list[FunctionFact]],
    ) -> str | None:
        expression_parts = observation.expression.split(".")
        candidate_names: list[str] = []
        if expression_parts[0] == "self" and observation.class_name:
            candidate_names.append(
                f"{observation.module}.{observation.class_name}."
                f"{'.'.join(expression_parts[1:])}"
            )
        elif expression_parts[0] in aliases:
            imported_module, imported_member = aliases[expression_parts[0]]
            tail = expression_parts[1:]
            if imported_member:
                candidate_names.append(
                    f"{imported_module}.{imported_member}.{'.'.join(tail)}".rstrip(".")
                )
            else:
                candidate_names.append(f"{imported_module}.{'.'.join(tail)}".rstrip("."))
        elif len(expression_parts) == 1:
            candidates = [
                function
                for function in functions_by_module.get(observation.module, [])
                if function.name.rsplit(".", 1)[-1] == observation.expression
            ]
            if len(candidates) == 1:
                return candidates[0].name
        else:
            candidate_names.append(f"{observation.module}.{observation.expression}")
        for candidate in candidate_names:
            if len(functions_by_name.get(candidate, [])) == 1:
                return candidate
        return None


class _PythonCollector(ast.NodeVisitor):
    def __init__(self, record: FileRecord, module: str) -> None:
        self.record = record
        self.module = module
        self.class_stack: list[str] = []
        self.function_stack: list[str] = []
        self.imports: list[_ImportObservation] = []
        self.functions: list[FunctionFact] = []
        self.calls: list[_CallObservation] = []
        self.secret_signals: list[SecretSignal] = []

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            local = alias.asname or alias.name.split(".", 1)[0]
            self.imports.append(
                _ImportObservation(
                    self.record.path,
                    self.module,
                    alias.name,
                    None,
                    local,
                    alias.asname or alias.name.split(".", 1)[0],
                    node.lineno,
                )
            )
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        is_package = Path(self.record.path).name == "__init__.py"
        package = self.module if is_package else self.module.rpartition(".")[0]
        base = _resolve_relative_module(package, node.level, node.module or "")
        for alias in node.names:
            if alias.name == "*":
                continue
            local = alias.asname or alias.name
            self.imports.append(
                _ImportObservation(
                    self.record.path,
                    self.module,
                    base,
                    alias.name,
                    local,
                    base,
                    node.lineno,
                )
            )
        self.generic_visit(node)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.class_stack.append(node.name)
        self.generic_visit(node)
        self.class_stack.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._record_function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._record_function(node)

    def visit_Assign(self, node: ast.Assign) -> None:
        self._record_secret_signal(node.targets, node.value, node.lineno)
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        self._record_secret_signal([node.target], node.value, node.lineno)
        self.generic_visit(node)

    def _record_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        name_parts = [self.module, *self.class_stack, node.name]
        qualified_name = ".".join(part for part in name_parts if part)
        end_line = node.end_lineno or node.lineno
        complexity = 1 + sum(
            isinstance(child, BRANCH_NODES)
            for child in _walk_without_nested_functions(node)
        )
        entrypoint_kind = _entrypoint_kind(node)
        self.functions.append(
            FunctionFact(
                name=qualified_name,
                module=self.module,
                path=self.record.path,
                start_line=node.lineno,
                end_line=end_line,
                complexity=complexity,
                entrypoint_kind=entrypoint_kind,
                evidence=_evidence(self.record, node.lineno, end_line),
            )
        )
        caller_class = ".".join(self.class_stack) if self.class_stack else None
        for call in _calls_in(node):
            self.calls.append(
                _CallObservation(
                    caller=qualified_name,
                    module=self.module,
                    class_name=caller_class,
                    expression=call.expression,
                    line=call.line,
                    path=self.record.path,
                )
            )
        self.function_stack.append(node.name)
        self.generic_visit(node)
        self.function_stack.pop()

    def _record_secret_signal(
        self, targets: list[ast.expr], value: ast.expr | None, line_number: int
    ) -> None:
        if not isinstance(value, ast.Constant) or not isinstance(value.value, str):
            return
        if len(value.value) < 8:
            return
        for target in targets:
            for name in _target_names(target):
                if SECRET_NAME.search(name):
                    self.secret_signals.append(
                        SecretSignal(
                            variable_name=name,
                            evidence=_evidence(self.record, line_number),
                        )
                    )


@dataclass(frozen=True)
class _CallName:
    expression: str
    line: int


class _CallCollector(ast.NodeVisitor):
    def __init__(self) -> None:
        self.calls: list[_CallName] = []
        self._root: ast.AST | None = None

    def visit_Call(self, node: ast.Call) -> None:
        name = _expression_name(node.func)
        if name:
            self.calls.append(_CallName(name, node.lineno))
        self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        if node is self._root:
            for statement in node.body:
                self.visit(statement)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        if node is self._root:
            for statement in node.body:
                self.visit(statement)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        return


def _calls_in(node: ast.FunctionDef | ast.AsyncFunctionDef) -> tuple[_CallName, ...]:
    collector = _CallCollector()
    collector._root = node
    collector.visit(node)
    return tuple(collector.calls)


def _walk_without_nested_functions(node: ast.AST) -> tuple[ast.AST, ...]:
    class Walker(ast.NodeVisitor):
        def __init__(self) -> None:
            self.nodes: list[ast.AST] = []

        def generic_visit(self, current: ast.AST) -> None:
            self.nodes.append(current)
            super().generic_visit(current)

        def visit_FunctionDef(self, current: ast.FunctionDef) -> None:
            if current is node:
                self.generic_visit(current)

        def visit_AsyncFunctionDef(self, current: ast.AsyncFunctionDef) -> None:
            if current is node:
                self.generic_visit(current)

        def visit_ClassDef(self, current: ast.ClassDef) -> None:
            return

    walker = Walker()
    walker.visit(node)
    return tuple(walker.nodes)


def _entrypoint_kind(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str | None:
    for decorator in node.decorator_list:
        name = _expression_name(decorator.func if isinstance(decorator, ast.Call) else decorator)
        if not name:
            continue
        decorator_name = name.rsplit(".", 1)[-1].casefold()
        if decorator_name in HTTP_DECORATORS:
            return "route HTTP candidate"
        if decorator_name == "command":
            return "commande CLI candidate"
        if decorator_name in WORKER_DECORATORS:
            return "worker/job candidate"
    return None


def _expression_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = _expression_name(node.value)
        return f"{parent}.{node.attr}" if parent else None
    return None


def _target_names(node: ast.expr) -> tuple[str, ...]:
    if isinstance(node, ast.Name):
        return (node.id,)
    if isinstance(node, (ast.Tuple, ast.List)):
        return tuple(name for element in node.elts for name in _target_names(element))
    return ()


def _module_name(path: str) -> str:
    parts = Path(path).with_suffix("").parts
    if parts and parts[0].casefold() == "src":
        parts = parts[1:]
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def _resolve_relative_module(current: str, level: int, imported: str) -> str:
    if level == 0:
        return imported
    parts = current.split(".") if current else []
    remove_count = max(level - 1, 0)
    if remove_count:
        parts = parts[: max(0, len(parts) - remove_count)]
    return ".".join(part for part in (*parts, imported) if part)


def _evidence(record: FileRecord, start_line: int, end_line: int | None = None) -> EvidenceRef:
    return EvidenceRef(
        path=record.path,
        start_line=start_line,
        end_line=end_line or start_line,
        sha256=record.sha256,
    )

import ast

from src.descriptors import ClassDescriptor, MethodDescriptor
from src.wrappers import ClassWrapper
from typing import List, Optional, Any, Set, Tuple, Dict, Union
import libcst as cst
import libcst.matchers as m
import importlib
from src.split.split_block import (
    StatementBlock,
    SplitContext,
    FirstBlockContext,
    LastBlockContext,
    IntermediateBlockContext,
    InvocationContext,
    Block,
)
from src.split.conditional_block import ConditionalBlock
from src.split.split_transform import RemoveAfterClassDefinition, SplitTransformer
from src.dataflow.event_flow import InvokeMethodRequest


class HasInteraction(cst.CSTVisitor):
    def __init__(self, node_to_analyze: cst.CSTNode, split_context: SplitContext):
        self.has_interaction = False
        self.split_context = split_context

        node_to_analyze.visit(self)

    def visit_Call(self, node: cst.Call):
        # Simple case: `item.update_stock()`
        # item is passed as parameter
        if m.matches(node.func, m.Attribute(m.Name(), m.Name())):
            attr: cst.Attribute = node.func

            callee: str = attr.value.value

            # Find callee class in the complete 'context'.
            desc: ClassDescriptor = self.split_context.class_descriptors.get(
                self.split_context.original_method_desc.input_desc[callee]
            )

            if desc is not None:
                self.has_interaction = True

    def get(self):
        return self.has_interaction


class SplitAnalyzer(cst.CSTVisitor):
    def __init__(
        self,
        class_node: cst.ClassDef,
        split_context: SplitContext,
        unparsed_statements: List[cst.CSTNode] = [],
        block_id_offset: int = 0,
        outer_block: bool = True,
    ):
        self.class_node: cst.ClassDef = class_node
        self.split_context: SplitContext = split_context
        self.unparsed_statements: List[cst.CSTNode] = (
            unparsed_statements
            if len(unparsed_statements) > 0
            else split_context.original_method_node.body.children
        )
        self.outer_block: bool = outer_block

        # Unparsed blocks
        self.statements: List[cst.BaseStatement] = []

        # Parsed blocks
        self.current_block_id: int = block_id_offset
        self.blocks: List[Block] = []

        # Unlinked blocks
        self.unlinked_blocks: List[Block] = []

        # Analyze this method.
        if self.outer_block:
            self._outer_analyze()
        else:
            self._inner_analyze()

    def _add_block(self, block: Block):
        [
            b.set_next_block(block) for b in self.unlinked_blocks
        ]  # TODO Consider adding all these for previous(block)

        self.unlinked_blocks = []
        self.blocks.append(block)

    def _analyze_statements(self):
        for stmt in self.unparsed_statements:
            stmt.visit(self)
            self.statements.append(stmt)

    def _get_previous_invocation(self) -> Optional[InvocationContext]:
        previous_invocation: Optional[InvocationContext] = None
        if len(self.blocks) > 0 and self.blocks[-1].split_context.current_invocation:
            previous_invocation = self.blocks[-1].split_context.current_invocation

        return previous_invocation

    def _get_previous_block(self) -> Optional[Block]:
        if len(self.blocks) > 0:
            return self.blocks[-1]
        return None

    def _inner_analyze(self):
        self._analyze_statements()

        self._add_block(
            StatementBlock(
                self.current_block_id,
                self.statements,
                IntermediateBlockContext.from_instance(
                    self.split_context,
                    current_invocation=None,
                    previous_invocation=self._get_previous_invocation(),
                ),
                self._get_previous_block(),
            )
        )

    def _outer_analyze(self):
        if not m.matches(self.split_context.original_method_node, m.FunctionDef()):
            raise AttributeError(
                f"Expected a function definition but got an {self.split_context.original_method_node}."
            )

        self._analyze_statements()
        self._add_block(
            StatementBlock(
                self.current_block_id,
                self.statements,
                LastBlockContext.from_instance(
                    self.split_context,
                    previous_invocation=self._get_previous_invocation(),
                ),
                self._get_previous_block(),
            )
        )

    def visit_Call(self, node: cst.Call):
        # Simple case: `item.update_stock()`
        # item is passed as parameter
        if m.matches(node.func, m.Attribute(m.Name(), m.Name())):
            attr: cst.Attribute = node.func

            callee: str = attr.value.value
            method: str = attr.attr.value

            # Find callee class in the complete 'context'.
            desc: ClassDescriptor = self.split_context.class_descriptors[
                self.split_context.original_method_desc.input_desc[callee]
            ]

            invocation_context = InvocationContext(
                desc, callee, method, desc.get_method_by_name(method), node.args
            )

            self._process_stmt_block_with_invocation(invocation_context)

    def visit_If(self, node: cst.If):
        if not HasInteraction(node, self.split_context).get():
            print("We don't need to identify this block.")
            return False
        else:
            if len(self.blocks) == 0:
                self._process_stmt_block_without_invocation()

            # Build conditional block:
            current_if: Union[cst.If] = node
            conditional_block: Optional[ConditionalBlock] = None
            last_body_block: List[Block] = []

            while isinstance(current_if, cst.If):
                # TODO We now assume there is a 'previous' block, always.
                conditional_block = ConditionalBlock(
                    self.current_block_id,
                    self.split_context,
                    node.test,
                    self.blocks[-1] if conditional_block is None else conditional_block,
                )
                self._add_block(conditional_block)
                self.current_block_id += 1

                # Build body of this if_block.
                analyze_if_body: SplitAnalyzer = SplitAnalyzer(
                    self.class_node,
                    self.split_context,
                    current_if.body.children,
                    block_id_offset=self.current_block_id,
                    outer_block=False,
                )

                # These are the blocks inside the if body.
                if_blocks: List[StatementBlock] = analyze_if_body.blocks

                # Link up first if_block, to conditional:
                if_blocks[0].set_previous_block(conditional_block)

                # We track a list of the latest block of each if-body, so that we can link it up to the block _after_
                # the if statement.
                last_body_block.append(if_blocks[-1])

                # Update outer-scope.
                self.blocks.extend(if_blocks)
                self.current_block_id = len(self.blocks)

                # Pick next if, else, or None.
                current_if = current_if.orelse

            if isinstance(current_if, cst.Else):
                else_stmt: cst.Else = node
                analyze_else_body: SplitAnalyzer = SplitAnalyzer(
                    self.class_node,
                    self.split_context,
                    else_stmt.body.children,
                    block_id_offset=self.current_block_id,
                    outer_block=False,
                )

                else_blocks: List[StatementBlock] = analyze_else_body.blocks

                # We connect the first block of this else body, to the last conditional.
                # We assume this conditional_block is not None, because you can't have an "else" clause
                # without an if or elif before it.
                else_blocks[0].set_next_block(conditional_block)

                # We track a list of the latest block of each if-body, so that we can link it up to the block _after_
                # the if statement.
                last_body_block.append(else_blocks[-1])

                # Update outer-scope.
                self.blocks.extend(else_blocks)
                self.current_block_id = len(self.blocks)

            print(f"Unlinked blocks: {[b.block_id for b in last_body_block]}")
            self.unlinked_blocks = last_body_block

        return False

    def _process_stmt_block_without_invocation(self):
        if self.current_block_id == 0:
            split_context = FirstBlockContext.from_instance(
                self.split_context,
                current_invocation=None,
            )
        else:
            split_context = IntermediateBlockContext.from_instance(
                self.split_context,
                previous_invocation=None,
                current_invocation=None,
            )

        self._process_stmt_block(split_context)

    def _process_stmt_block_with_invocation(
        self, invocation_context: InvocationContext
    ):
        if self.current_block_id == 0:
            split_context = FirstBlockContext.from_instance(
                self.split_context,
                current_invocation=invocation_context,
            )
        else:
            split_context = IntermediateBlockContext.from_instance(
                self.split_context,
                previous_invocation=self._get_previous_invocation(),
                current_invocation=invocation_context,
            )

        self._process_stmt_block(split_context)

    def _process_stmt_block(self, split_context: SplitContext):
        split_block = StatementBlock(
            self.current_block_id,
            self.statements,
            split_context,
            previous_block=None if len(self.blocks) == 0 else self.blocks[-1],
        )
        self._add_block(split_block)

        # Update local state.
        self.statements = []
        self.current_block_id += 1


class Split:
    def __init__(
        self, descriptors: List[ClassDescriptor], wrappers: List[ClassWrapper]
    ):
        self.wrappers = wrappers
        self.descriptors = descriptors
        self.name_to_descriptor = {desc.class_name: desc for desc in self.descriptors}

    def split_methods(self):
        for i, desc in enumerate(self.descriptors):
            updated_methods: Dict[str, List[StatementBlock]] = {}
            for method in desc.methods_dec:
                if method.has_links():
                    print(
                        f"{method.method_name} has links to other classes/functions. Now analyzing:"
                    )

                    analyzer: SplitAnalyzer = SplitAnalyzer(
                        desc.class_node,
                        SplitContext(
                            self.name_to_descriptor,
                            desc.expression_provider,
                            method.method_node,
                            method,
                            desc,
                        ),
                        method.method_node.body.children,
                    )

                    parsed_stmts: List[StatementBlock] = analyzer.blocks
                    updated_methods[method.method_name] = parsed_stmts

                    method.split_function(parsed_stmts)

            if len(updated_methods) > 0:
                remove_after_class_def = RemoveAfterClassDefinition(desc.class_name)

                modified_tree = desc.module_node.visit(remove_after_class_def)

                modified_tree = modified_tree.visit(
                    SplitTransformer(desc.class_name, updated_methods)
                )

                print(modified_tree.code)

                # Recompile the code and set the code in the wrapper.
                exec(compile(modified_tree.code, "", mode="exec"), globals(), globals())
                self.wrappers[i].cls = globals()[desc.class_name]

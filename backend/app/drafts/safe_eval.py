"""Evaluate an answer expression without exec/eval (answer keys recomputed in code, §10).

Only numbers, the problem's given names, + - * / // % **, unary +/-, and a
whitelist of math functions are allowed. Anything else raises UnsafeExpression.
"""

from __future__ import annotations

import ast
import math
import operator
from collections.abc import Callable
from typing import Any

_BIN: dict[type, Callable[[Any, Any], Any]] = {
    ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv, ast.Mod: operator.mod, ast.Pow: operator.pow,
}
_UN: dict[type, Callable[[Any], Any]] = {ast.UAdd: operator.pos, ast.USub: operator.neg}
_FUNCS: dict[str, Callable[..., Any]] = {
    "sqrt": math.sqrt, "log": math.log, "ln": math.log, "log10": math.log10, "log2": math.log2, "exp": math.exp,
    "abs": abs, "min": min, "max": max, "round": round, "factorial": math.factorial, "comb": math.comb,
    "perm": math.perm, "floor": math.floor, "ceil": math.ceil, "sin": math.sin, "cos": math.cos, "tan": math.tan,
}
_CONSTS = {"pi": math.pi, "e": math.e}
_MAX_POW = 1000


class UnsafeExpression(ValueError):
    pass


def evaluate(expr: str, names: dict[str, float]) -> float:
    if len(expr) > 500:
        raise UnsafeExpression("Expression too long.")
    try:
        tree = ast.parse(expr.replace("^", "**"), mode="eval")
    except SyntaxError as e:
        raise UnsafeExpression(f"Not a valid expression: {e.msg}") from e
    env = {**_CONSTS, **names}

    def ev(node: ast.AST) -> float:
        if isinstance(node, ast.Expression):
            return ev(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
            return node.value
        if isinstance(node, ast.Name):
            if node.id in env:
                return env[node.id]
            raise UnsafeExpression(f"Unknown name '{node.id}'.")
        if isinstance(node, ast.BinOp) and type(node.op) in _BIN:
            left, right = ev(node.left), ev(node.right)
            if isinstance(node.op, ast.Pow) and abs(right) > _MAX_POW:
                raise UnsafeExpression("Exponent too large.")
            return _BIN[type(node.op)](left, right)
        if isinstance(node, ast.UnaryOp) and type(node.op) in _UN:
            return _UN[type(node.op)](ev(node.operand))
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in _FUNCS and not node.keywords:
            args = [ev(a) for a in node.args]
            if node.func.id in {"factorial", "comb", "perm"}:
                if any(a > 1000 or a != int(a) for a in args):
                    raise UnsafeExpression("Integer argument too large or not whole.")
                args = [int(a) for a in args]
            return _FUNCS[node.func.id](*args)
        raise UnsafeExpression(f"'{ast.unparse(node)}' is not allowed.")

    try:
        result = ev(tree)
    except (ZeroDivisionError, OverflowError, ValueError, TypeError) as e:
        if isinstance(e, UnsafeExpression):
            raise
        raise UnsafeExpression(f"Could not compute: {e}") from e
    return float(result)

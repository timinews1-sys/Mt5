import ast
import math
from dataclasses import dataclass
from typing import Protocol


class StrategyError(ValueError):
    pass


class StrategyContext(Protocol):
    def read_attr(self, name: str) -> object: ...

    def call(self, name: str, args: list[object]) -> object: ...


_METHODS = {
    "sma",
    "ema",
    "rsi",
    "signal",
    "plot",
    "buy",
    "sell",
    "close_position",
}
_PROPERTIES = {
    "open",
    "high",
    "low",
    "close_price",
    "volume",
    "position",
    "index",
}
_STATEMENT_NODES = (ast.Assign, ast.If, ast.Expr, ast.Pass)
_EXPRESSION_NODES = (
    ast.Constant,
    ast.Name,
    ast.Attribute,
    ast.Call,
    ast.BinOp,
    ast.UnaryOp,
    ast.BoolOp,
    ast.Compare,
)
_BINARY_OPERATORS = {
    ast.Add: lambda left, right: left + right,
    ast.Sub: lambda left, right: left - right,
    ast.Mult: lambda left, right: left * right,
    ast.Div: lambda left, right: left / right,
    ast.Mod: lambda left, right: left % right,
}
_UNARY_OPERATORS = {
    ast.UAdd: lambda value: +value,
    ast.USub: lambda value: -value,
    ast.Not: lambda value: not value,
}
_COMPARE_OPERATORS = {
    ast.Eq: lambda left, right: left == right,
    ast.NotEq: lambda left, right: left != right,
    ast.Lt: lambda left, right: left < right,
    ast.LtE: lambda left, right: left <= right,
    ast.Gt: lambda left, right: left > right,
    ast.GtE: lambda left, right: left >= right,
    ast.Is: lambda left, right: left is right,
    ast.IsNot: lambda left, right: left is not right,
}
_BINARY_OPERATORS_BY_NAME = {
    operator.__name__: implementation
    for operator, implementation in _BINARY_OPERATORS.items()
}
_UNARY_OPERATORS_BY_NAME = {
    operator.__name__: implementation
    for operator, implementation in _UNARY_OPERATORS.items()
}
_COMPARE_OPERATORS_BY_NAME = {
    operator.__name__: implementation
    for operator, implementation in _COMPARE_OPERATORS.items()
}


@dataclass(frozen=True)
class StrategyProgram:
    body: tuple[tuple[object, ...], ...]

    def run(self, context: StrategyContext) -> None:
        variables: dict[str, object] = {}
        for statement in self.body:
            _execute(statement, variables, context)


def compile_strategy(source: str) -> StrategyProgram:
    if not isinstance(source, str):
        raise StrategyError("Strategy script must be text.")
    if len(source) > 16_384:
        raise StrategyError("Strategy script exceeds the 16 KB limit.")
    if not source.strip():
        raise StrategyError("Strategy script is empty.")

    try:
        module = ast.parse(source, mode="exec")
    except SyntaxError as exc:
        line = f" on line {exc.lineno}" if exc.lineno is not None else ""
        raise StrategyError(f"Invalid Python syntax{line}: {exc.msg}") from exc
    except RecursionError as exc:
        raise StrategyError("Strategy script nesting is too deep.") from exc

    if len(module.body) != 1 or not isinstance(module.body[0], ast.FunctionDef):
        raise StrategyError("Define exactly one function: def on_bar(ctx):")

    function = module.body[0]
    if function.name != "on_bar":
        raise StrategyError("The strategy entry point must be named on_bar.")
    if (
        function.decorator_list
        or function.returns is not None
        or function.type_comment is not None
        or getattr(function, "type_params", ())
    ):
        raise StrategyError(
            "Decorators, return annotations, type comments, and type parameters are not supported."
        )
    arguments = function.args
    if (
        len(arguments.args) != 1
        or arguments.args[0].arg != "ctx"
        or arguments.posonlyargs
        or arguments.vararg is not None
        or arguments.kwonlyargs
        or arguments.kwarg is not None
        or arguments.defaults
        or arguments.kw_defaults
    ):
        raise StrategyError("The entry point must have exactly one argument: ctx.")
    if not function.body:
        raise StrategyError("The on_bar function must contain at least one statement.")

    nodes = list(ast.walk(function))
    if len(nodes) > 300:
        raise StrategyError("Strategy script is too complex (maximum 300 syntax nodes).")
    _validate_statements(function.body)
    return StrategyProgram(_compile_statements(function.body))


def _validate_statements(statements: list[ast.stmt]) -> None:
    for statement in statements:
        if not isinstance(statement, _STATEMENT_NODES):
            raise StrategyError(f"{type(statement).__name__} statements are not supported.")
        if isinstance(statement, ast.Assign):
            if len(statement.targets) != 1 or not isinstance(statement.targets[0], ast.Name):
                raise StrategyError("Only simple variable assignments are supported.")
            if statement.targets[0].id == "ctx" or statement.targets[0].id.startswith("__"):
                raise StrategyError("That variable name is reserved.")
            _validate_expression(statement.value)
        elif isinstance(statement, ast.If):
            _validate_expression(statement.test)
            _validate_statements(statement.body)
            _validate_statements(statement.orelse)
        elif isinstance(statement, ast.Expr):
            if not isinstance(statement.value, ast.Call):
                raise StrategyError("Expression statements must call a strategy API method.")
            _validate_expression(statement.value)


def _validate_expression(expression: ast.expr) -> None:
    if not isinstance(expression, _EXPRESSION_NODES):
        raise StrategyError(f"{type(expression).__name__} expressions are not supported.")
    if isinstance(expression, ast.Constant):
        value = expression.value
        if not (value is None or isinstance(value, (bool, int, float, str))):
            raise StrategyError("Only simple numeric, text, boolean, and None values are allowed.")
        if isinstance(value, str) and len(value) > 256:
            raise StrategyError("Text literals may not exceed 256 characters.")
        if isinstance(value, int) and not isinstance(value, bool) and abs(value) > 2**53:
            raise StrategyError("Integer literals are too large.")
        if isinstance(value, float) and not math.isfinite(value):
            raise StrategyError("Numeric literals must be finite.")
    elif isinstance(expression, ast.Name):
        if expression.id.startswith("__"):
            raise StrategyError("Names beginning with double underscores are not supported.")
    elif isinstance(expression, ast.Attribute):
        if not isinstance(expression.value, ast.Name) or expression.value.id != "ctx":
            raise StrategyError("Only documented ctx properties and methods are available.")
        if expression.attr not in _PROPERTIES | _METHODS:
            raise StrategyError(f"ctx.{expression.attr} is not available.")
    elif isinstance(expression, ast.Call):
        if (
            not isinstance(expression.func, ast.Attribute)
            or not isinstance(expression.func.value, ast.Name)
            or expression.func.value.id != "ctx"
            or expression.func.attr not in _METHODS
        ):
            raise StrategyError("Only documented ctx methods may be called.")
        if expression.keywords:
            raise StrategyError("Keyword arguments are not supported.")
        for argument in expression.args:
            _validate_expression(argument)
    elif isinstance(expression, ast.BinOp):
        if type(expression.op) not in _BINARY_OPERATORS:
            raise StrategyError(f"{type(expression.op).__name__} is not supported.")
        _validate_expression(expression.left)
        _validate_expression(expression.right)
    elif isinstance(expression, ast.UnaryOp):
        if type(expression.op) not in _UNARY_OPERATORS:
            raise StrategyError(f"{type(expression.op).__name__} is not supported.")
        _validate_expression(expression.operand)
    elif isinstance(expression, ast.BoolOp):
        if not isinstance(expression.op, (ast.And, ast.Or)):
            raise StrategyError("Only 'and' and 'or' boolean operators are supported.")
        for value in expression.values:
            _validate_expression(value)
    elif isinstance(expression, ast.Compare):
        if not expression.ops or len(expression.ops) != len(expression.comparators):
            raise StrategyError("Invalid comparison expression.")
        for operator, comparator in zip(expression.ops, expression.comparators):
            if type(operator) not in _COMPARE_OPERATORS:
                raise StrategyError(f"{type(operator).__name__} comparisons are not supported.")
            if isinstance(operator, (ast.Is, ast.IsNot)) and not (
                isinstance(comparator, ast.Constant) and comparator.value is None
            ):
                raise StrategyError("'is' comparisons are only supported with None.")
            _validate_expression(comparator)
        _validate_expression(expression.left)


def _compile_statements(
    statements: list[ast.stmt],
) -> tuple[tuple[object, ...], ...]:
    compiled = []
    for statement in statements:
        if isinstance(statement, ast.Pass):
            compiled.append(("PASS",))
        elif isinstance(statement, ast.Assign):
            target = statement.targets[0]
            assert isinstance(target, ast.Name)
            compiled.append(("ASSIGN", target.id, _compile_expression(statement.value)))
        elif isinstance(statement, ast.If):
            compiled.append(
                (
                    "IF",
                    _compile_expression(statement.test),
                    _compile_statements(statement.body),
                    _compile_statements(statement.orelse),
                )
            )
        elif isinstance(statement, ast.Expr):
            compiled.append(("EXPR", _compile_expression(statement.value)))
        else:
            raise StrategyError(f"{type(statement).__name__} statements are not supported.")
    return tuple(compiled)


def _compile_expression(expression: ast.expr) -> tuple[object, ...]:
    if isinstance(expression, ast.Constant):
        return ("CONST", expression.value)
    if isinstance(expression, ast.Name):
        return ("NAME", expression.id)
    if isinstance(expression, ast.Attribute):
        return ("ATTRIBUTE", expression.attr)
    if isinstance(expression, ast.Call):
        assert isinstance(expression.func, ast.Attribute)
        return (
            "CALL",
            expression.func.attr,
            tuple(_compile_expression(argument) for argument in expression.args),
        )
    if isinstance(expression, ast.BinOp):
        return (
            "BINARY",
            type(expression.op).__name__,
            _compile_expression(expression.left),
            _compile_expression(expression.right),
        )
    if isinstance(expression, ast.UnaryOp):
        return (
            "UNARY",
            type(expression.op).__name__,
            _compile_expression(expression.operand),
        )
    if isinstance(expression, ast.BoolOp):
        return (
            "BOOLEAN",
            type(expression.op).__name__,
            tuple(_compile_expression(value) for value in expression.values),
        )
    if isinstance(expression, ast.Compare):
        return (
            "COMPARE",
            _compile_expression(expression.left),
            tuple(
                (type(operator).__name__, _compile_expression(comparator))
                for operator, comparator in zip(expression.ops, expression.comparators)
            ),
        )
    raise StrategyError(f"{type(expression).__name__} expressions are not supported.")


def _execute(
    statement: tuple[object, ...],
    variables: dict[str, object],
    context: StrategyContext,
) -> None:
    opcode = statement[0]
    if opcode == "PASS":
        return
    if opcode == "ASSIGN":
        _name, target, expression = statement
        assert isinstance(target, str)
        variables[target] = _evaluate(expression, variables, context)
        return
    if opcode == "IF":
        _name, test, body, orelse = statement
        assert isinstance(body, tuple) and isinstance(orelse, tuple)
        branch = body if _evaluate(test, variables, context) else orelse
        for child in branch:
            _execute(child, variables, context)
        return
    if opcode == "EXPR":
        _evaluate(statement[1], variables, context)
        return
    raise StrategyError(f"Unknown strategy instruction: {opcode}.")


def _evaluate(
    expression: tuple[object, ...],
    variables: dict[str, object],
    context: StrategyContext,
) -> object:
    opcode = expression[0]
    if opcode == "CONST":
        return expression[1]
    if opcode == "NAME":
        name = expression[1]
        assert isinstance(name, str)
        if name == "ctx":
            return context
        try:
            return variables[name]
        except KeyError as exc:
            raise StrategyError(f"Variable '{name}' is used before assignment.") from exc
    if opcode == "ATTRIBUTE":
        name = expression[1]
        assert isinstance(name, str)
        return context.read_attr(name)
    if opcode == "CALL":
        method, arguments = expression[1], expression[2]
        assert isinstance(method, str) and isinstance(arguments, tuple)
        args = [_evaluate(argument, variables, context) for argument in arguments]
        try:
            return context.call(method, args)
        except (ArithmeticError, TypeError) as exc:
            raise StrategyError(f"Invalid call to ctx.{method}: {exc}") from exc
    if opcode == "BINARY":
        operator, left_expression, right_expression = expression[1:]
        assert isinstance(operator, str)
        left = _numeric_value(_evaluate(left_expression, variables, context))
        right = _numeric_value(_evaluate(right_expression, variables, context))
        try:
            result = _BINARY_OPERATORS_BY_NAME[operator](left, right)
        except (ArithmeticError, TypeError) as exc:
            raise StrategyError(f"Invalid arithmetic expression: {exc}") from exc
        return _numeric_value(result)
    if opcode == "UNARY":
        operator, operand = expression[1:]
        assert isinstance(operator, str)
        value = _evaluate(operand, variables, context)
        if operator != "Not":
            value = _numeric_value(value)
        try:
            return _UNARY_OPERATORS_BY_NAME[operator](value)
        except TypeError as exc:
            raise StrategyError(f"Invalid unary expression: {exc}") from exc
    if opcode == "BOOLEAN":
        operator, expressions = expression[1], expression[2]
        assert isinstance(operator, str) and isinstance(expressions, tuple)
        if operator == "And":
            result: object = True
            for value_expression in expressions:
                result = _evaluate(value_expression, variables, context)
                if not result:
                    return result
            return result
        result = False
        for value_expression in expressions:
            result = _evaluate(value_expression, variables, context)
            if result:
                return result
        return result
    if opcode == "COMPARE":
        left_expression, comparisons = expression[1], expression[2]
        assert isinstance(comparisons, tuple)
        left = _evaluate(left_expression, variables, context)
        for operator, comparator in comparisons:
            right = _evaluate(comparator, variables, context)
            try:
                matched = _COMPARE_OPERATORS_BY_NAME[operator](left, right)
            except TypeError as exc:
                raise StrategyError(f"Invalid comparison: {exc}") from exc
            if not matched:
                return False
            left = right
        return True
    raise StrategyError(f"Unknown strategy expression: {opcode}.")


def _numeric_value(value: object) -> int | float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise StrategyError("Arithmetic operators require numeric values.")
    if isinstance(value, int):
        if value.bit_length() > 333:
            raise StrategyError("Numeric value is outside the supported range.")
    elif not math.isfinite(value) or abs(value) > 1e100:
        raise StrategyError("Numeric value is outside the supported range.")
    return value

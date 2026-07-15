import ast
import json
import math
import operator as op

# Define strictly allowed operators
SAFE_OPERATORS = {
    ast.Add: op.add,
    ast.Sub: op.sub,
    ast.Mult: op.mul,
    ast.Div: op.truediv,
    ast.FloorDiv: op.floordiv,
    ast.Mod: op.mod,
    ast.Pow: op.pow,
    ast.USub: op.neg,  # e.g., -5
    ast.UAdd: op.pos,  # e.g., +5
}

# Define strictly allowed functions and constants
SAFE_FUNCTIONS = {
    "sqrt": math.sqrt,
    "abs": abs,
    "round": round,
    "pow": pow,
    "pi": math.pi,
    "e": math.e,
}


def _eval_ast_node(node):
    """
    Recursively evaluate an AST node. Only allowed nodes will be processed.
    """
    # Numbers / Constants (Python 3.8+)
    if isinstance(node, ast.Constant):
        if not isinstance(node.value, (int, float)):
            raise TypeError("Only numeric constants are allowed.")
        return node.value

    # Legacy Python compatibility for older numbers
    elif isinstance(node, ast.Num):
        return node.n

    # Binary Operations (e.g., 2 + 2)
    elif isinstance(node, ast.BinOp):
        op_type = type(node.op)
        if op_type not in SAFE_OPERATORS:
            raise TypeError(f"Operator '{op_type.__name__}' is not supported.")

        left_val = _eval_ast_node(node.left)
        right_val = _eval_ast_node(node.right)

        # Prevent CPU-locking operations like 999999 ** 999999
        if op_type is ast.Pow and (left_val > 10000 or right_val > 1000):
            raise ValueError("Exceeded maximum safe power limits.")

        return SAFE_OPERATORS[op_type](left_val, right_val)

    # Unary Operations (e.g., -5)
    elif isinstance(node, ast.UnaryOp):
        op_type = type(node.op)
        if op_type not in SAFE_OPERATORS:
            raise TypeError(f"Unary operator '{op_type.__name__}' is not supported.")
        return SAFE_OPERATORS[op_type](_eval_ast_node(node.operand))

    # Whitelisted Function Calls (e.g., sqrt(144))
    elif isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name):
            raise TypeError("Unsupported function call format.")

        func_name = node.func.id
        if func_name not in SAFE_FUNCTIONS:
            raise ValueError(f"Function '{func_name}' is not allowed.")

        args = [_eval_ast_node(arg) for arg in node.args]
        return SAFE_FUNCTIONS[func_name](*args)

    # Whitelisted Name lookups (e.g., pi)
    elif isinstance(node, ast.Name):
        name = node.id
        if name not in SAFE_FUNCTIONS:
            raise ValueError(f"Constant/Variable '{name}' is not allowed.")
        return SAFE_FUNCTIONS[name]

    # Block everything else
    else:
        raise TypeError(f"Unsupported syntax: {type(node).__name__}")


def calculate(expression: str) -> str:
    """
    Perform a safe mathematical calculation.

    :param expression: Math expression, e.g. '2+2', '100*0.15', 'sqrt(144)'
    :return: Calculation result as JSON string.
    """
    try:
        # Strip all whitespace for uniform parsing
        cleaned = expression.replace(" ", "")

        # Parse the mathematical string into an AST tree
        tree = ast.parse(cleaned, mode="eval")

        # Evaluate the tree
        result = _eval_ast_node(tree.body)

        # Keep precision clean
        if isinstance(result, float) and result.is_integer():
            result = int(result)

        return json.dumps({"expression": expression, "result": result})

    except Exception as e:
        return json.dumps({"expression": expression, "error": f"Invalid calculation: {str(e)}"})
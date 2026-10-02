"""A bounded desktop instruction interpreter, never Python exec/eval.

This restricts the language, not the effects of desktop input. Calling it still
requires trusted UI approval because typing/clicking can affect other programs.
"""
import ast
import time

METHODS = {"click", "doubleClick", "rightClick", "moveTo", "scroll", "press", "hotkey", "write", "size", "position"}
NODES = (ast.Module, ast.Expr, ast.Assign, ast.Name, ast.Load, ast.Store,
         ast.Call, ast.Attribute, ast.Constant, ast.List, ast.Tuple, ast.keyword,
         ast.UnaryOp, ast.USub)

def validate(code):
    if not isinstance(code, str) or len(code) > 16000:
        raise ValueError("Code must be at most 16000 characters")
    tree = ast.parse(code)
    if len(tree.body) > 100 or sum(1 for _ in ast.walk(tree)) > 1000:
        raise ValueError("Instruction limit exceeded")
    for node in ast.walk(tree):
        if not isinstance(node, NODES):
            raise ValueError(f"Forbidden syntax: {type(node).__name__}")
        if isinstance(node, ast.Name) and node.id.startswith("_"):
            raise ValueError("Private names forbidden")
        if isinstance(node, ast.Constant) and not isinstance(node.value, (str, int, float, bool, type(None))):
            raise ValueError("Unsupported constant")
        if isinstance(node, ast.Attribute):
            if not isinstance(node.value, ast.Name) or not (
                node.value.id == "pyautogui" and node.attr in METHODS or
                node.value.id == "time" and node.attr == "sleep"):
                raise ValueError("Attribute not allowlisted")
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                if node.func.id != "print":
                    raise ValueError("Function not allowlisted")
            elif not isinstance(node.func, ast.Attribute):
                raise ValueError("Indirect calls forbidden")
            if any(k.arg is None for k in node.keywords):
                raise ValueError("Keyword expansion forbidden")
        if isinstance(node, ast.Assign):
            if len(node.targets) != 1 or not isinstance(node.targets[0], ast.Name) or node.targets[0].id in ("print", "time", "pyautogui"):
                raise ValueError("Assignment target forbidden")
    return tree

def run(code, desktop=None):
    tree = validate(code)
    if desktop is None:
        import pyautogui as desktop
    output, variables = [], {}
    deadline = time.monotonic() + 15
    def value(node):
        if time.monotonic() > deadline:
            raise TimeoutError("Desktop instruction time limit reached; partial actions may have occurred")
        if isinstance(node, ast.Constant):
            return node.value
        if isinstance(node, (ast.List, ast.Tuple)):
            return [value(e) for e in node.elts]
        if isinstance(node, ast.UnaryOp):
            return -value(node.operand)
        if isinstance(node, ast.Name) and node.id in variables:
            return variables[node.id]
        if isinstance(node, ast.Call):
            args = [value(a) for a in node.args]
            kwargs = {k.arg: value(k.value) for k in node.keywords}
            if isinstance(node.func, ast.Name):
                output.append(" ".join(str(a) for a in args)[:2000])
                return None
            if node.func.value.id == "time":
                if kwargs or len(args) != 1 or not isinstance(args[0], (int, float)) or not 0 <= args[0] <= 2:
                    raise ValueError("Sleep must be between zero and two seconds")
                time.sleep(args[0])
                return None
            if node.func.attr == "write" and (not args or not isinstance(args[0], str) or len(args[0]) > 256):
                raise ValueError("Typed text is limited to 256 characters")
            if node.func.attr == "press" and args and isinstance(args[0], list) and len(args[0]) > 10:
                raise ValueError("Key sequence is limited to 10 keys")
            for key in ("duration", "interval"):
                if key in kwargs and (not isinstance(kwargs[key], (int, float)) or not 0 <= kwargs[key] <= (.01 if key == "interval" else .2)):
                    raise ValueError("Input duration/interval exceeds limit")
            if "presses" in kwargs and (not isinstance(kwargs["presses"], int) or not 1 <= kwargs["presses"] <= 10):
                raise ValueError("Too many key presses")
            if len(str(args)) > 1000:
                raise ValueError("Input argument limit exceeded")
            # positional duration/repeat arguments would bypass keyword bounds.
            caps = {"click": 2, "doubleClick": 2, "rightClick": 2, "moveTo": 2,
                    "scroll": 1, "press": 1, "hotkey": 5, "write": 1, "size": 0, "position": 0}
            if len(args) > caps[node.func.attr]:
                raise ValueError("Too many positional arguments")
            allowed = {"duration", "interval", "presses"}
            if any(k not in allowed for k in kwargs):
                raise ValueError("Unsupported input option")
            return getattr(desktop, node.func.attr)(*args, **kwargs)
        raise ValueError("Unsupported expression")
    for statement in tree.body:
        if isinstance(statement, ast.Assign):
            variables[statement.targets[0].id] = value(statement.value)
        else:
            value(statement.value)
    return "\n".join(output) or "Desktop instructions issued; verify the target application."

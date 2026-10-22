"""Inventory real route declarations and compare TallerPlusWEB's HTTP calls.

This is a static route audit, not a claim of payload or session compatibility.
Exit code 1 with --check indicates missing routes; 2 indicates invalid input.
"""
import argparse
import ast
import json
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
METHODS = {"get", "post", "put", "patch", "delete", "options", "head"}


def backend_routes(path):
    routes = []
    tree = ast.parse(path.read_text(encoding="utf-8"))
    prefix = ""
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "APIRouter":
            prefix = next((item.value.value for item in node.keywords if item.arg == "prefix"
                and isinstance(item.value, ast.Constant)), "")
    for function in ast.walk(tree):
        if not isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for decorator in function.decorator_list:
            if (isinstance(decorator, ast.Call) and isinstance(decorator.func, ast.Attribute)
                    and isinstance(decorator.func.value, ast.Name) and decorator.func.value.id in {"app", "router"}
                    and decorator.func.attr in METHODS and decorator.args
                    and isinstance(decorator.args[0], ast.Constant)):
                routes.append({"method": decorator.func.attr.upper(), "path": prefix + decorator.args[0].value,
                    "file": path.relative_to(ROOT).as_posix(), "line": decorator.lineno})
    return sorted(routes, key=lambda item: (item["path"], item["method"]))


def frontend_calls(path):
    # customerApi exports one request per line; fail visibly if that format changes.
    calls = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not re.search(r"export const \w+.*=> request", line):
            continue
        match = re.search(r"\('/([^']+)'(.*)\);?\s*$", line)
        if not match:
            raise ValueError(f"Unsupported HTTP declaration at {path}:{line_number}")
        route, tail = match.groups()
        calls.append({"method": "POST" if tail.lstrip().startswith(",") else "GET",
            "path": "/api/" + route, "line": line_number})
    if not calls:
        raise ValueError(f"No frontend HTTP calls found in {path}")
    return calls


def matches(template, path):
    pattern = re.sub(r"\{[^}]+\}", "[^/]+", template)
    return re.fullmatch(pattern, path) is not None


def audit(frontend):
    inventory = {service.name: backend_routes(service / "app.py") + (backend_routes(service / "web.py") if (service / "web.py").exists() else [])
        for service in sorted((ROOT / "services").iterdir()) if (service / "app.py").exists()}
    gateway = inventory["api_gateway"]
    calls = frontend_calls(frontend / "src" / "services" / "customerApi.ts")
    for call in calls:
        call["gateway_exact_route"] = any(route["method"] == call["method"]
            and matches(route["path"], call["path"]) for route in gateway)
        call["gateway_route_after_stripping_api"] = any(route["method"] == call["method"]
            and matches(route["path"], call["path"].removeprefix("/api")) for route in gateway)
    missing = sorted({(call["method"], call["path"]) for call in calls
        if not call["gateway_exact_route"] and not call["gateway_route_after_stripping_api"]})
    return {"scope": "Static HTTP route overlap only; schemas, auth and local storage require separate review.",
        "backend_routes": inventory, "frontend_calls": calls,
        "summary": {"gateway_route_count": len(gateway), "frontend_call_count": len(calls),
            "frontend_unique_route_count": len({(call['method'], call['path']) for call in calls}),
            "exact_route_overlap": sum(call["gateway_exact_route"] for call in calls),
            "missing_even_after_stripping_api": [f"{method} {path}" for method, path in missing]}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--frontend", type=Path, default=ROOT.parent / "TallerPlusWEB")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    try:
        report = audit(args.frontend.resolve())
    except (OSError, ValueError) as error:
        parser.error(str(error))
    if args.output:
        args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(report["summary"], indent=2, ensure_ascii=False))
    return 1 if args.check and report["summary"]["missing_even_after_stripping_api"] else 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Explicit demo roles. This is authorization by declared role, not authentication."""
import re

def permitted(role, method, path):
    if role not in ("reviewer", "manager"): return False
    if method == "GET" and path in ("/api/field-catalog","/api/reason-catalog"): return True
    if role == "reviewer":
        if method == "GET":
            return path == "/api/exports/decisions" or bool(re.fullmatch(r"/api/requests(?:/[^/]+(?:/(?:audit|history|chargeback-risk|policy-evaluation))?)?",path))
        return method == "POST" and bool(re.fullmatch(r"/api/requests/[^/]+/(?:workflow|decisions|evidence|resolve|correct|outcomes|reopen)",path))
    # Managers inspect examples; operational review belongs to the reviewer workspace.
    if path.startswith("/api/requests") and method != "GET": return False
    return True

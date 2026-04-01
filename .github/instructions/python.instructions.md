---
description: "Use when writing or modifying Python source code in this project. Covers imports, typing, module structure, and error handling conventions."
applyTo: "src/**/*.py"
---

# Python Code Standards

- Start every module with `from __future__ import annotations`
- Add type hints to all function signatures and return types
- Use `str | None` union syntax, not `Optional[str]`
- Prefer plain functions over classes unless state is needed
- Use Pydantic v2 `BaseModel` for API request/response schemas
- Use `@dataclass` for internal value objects
- Keep imports grouped: stdlib → third-party → local (relative with `.`)
- Use relative imports within `pst_agent` package (`from .config import Settings`)
- Generate IDs with `new_id(prefix)` from `utils.py`
- Clean all extracted text through `clean_text()` before storage
- Never catch bare `Exception` in production paths unless re-raised with context

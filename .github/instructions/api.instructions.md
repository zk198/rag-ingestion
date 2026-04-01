---
description: "Use when working on the REST API endpoints, request/response models, or FastAPI configuration."
applyTo: "src/pst_agent/api.py"
---

# API Conventions

- All request bodies use Pydantic `BaseModel` with `Field` constraints
- Raise `HTTPException` with appropriate status codes, not bare exceptions
- Wrap service calls in try/except and map to HTTP errors:
  - `FileNotFoundError` → 404
  - `ValueError` → 400
  - Generic errors → 500
- Endpoints follow REST naming: nouns for resources, POST for actions
- File uploads use `UploadFile` with form fields, not JSON body
- Source metadata (`account_email`, `account_type`, `display_name`, `description`) is accepted on ingest and upload endpoints

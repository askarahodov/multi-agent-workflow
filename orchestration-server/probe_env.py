import fastapi, sqlalchemy, pydantic, aiosqlite, httpx, jsonschema
from openapi_spec_validator import validate
print("fastapi", fastapi.__version__)
print("sqlalchemy", sqlalchemy.__version__)
print("pydantic", pydantic.VERSION)
print("ok")

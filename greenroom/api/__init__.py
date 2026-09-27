"""The HTTP surface. Stateless, and never calls a model inside a request handler."""

from fastapi import FastAPI

app = FastAPI(title="Greenroom")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}

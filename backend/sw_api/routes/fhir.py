"""Authenticated, read-only hospital interoperability endpoints."""
import logging

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse

from ..fhir import capability_statement, export_bundle
from . import Deps

LOG = logging.getLogger(__name__)


def register(app: FastAPI, d: Deps) -> None:
    def response(body: dict) -> JSONResponse:
        return JSONResponse(body, media_type="application/fhir+json", headers={"Cache-Control": "no-store"})

    @app.get("/api/fhir/Bundle", tags=["FHIR"])
    async def bundle(since: int = Query(default=0, ge=0, le=253402300799999),
                     bed: str | None = Query(default=None, pattern=r"^B(0[1-9]|1[0-2])$"),
                     identity=Depends(d.user)):
        if bed is not None:
            d.require_bed(bed)
        generation = d.runtime.ingest.generation
        try:
            body = await export_bundle(d.runtime, since, bed)
        except Exception:
            LOG.exception("FHIR export read failed")
            raise HTTPException(503, "FHIR export unavailable; retry the read") from None
        if generation != d.runtime.ingest.generation:
            raise HTTPException(409, "Ward reset during FHIR export; retry the read")
        return response(body)

    @app.get("/api/fhir/metadata", tags=["FHIR"])
    async def metadata(identity=Depends(d.user)):
        return response(capability_statement(d.runtime.clock.ms()))

"""/api/digests: weekly and monthly digests (docs/api.md "Digests API")."""

from __future__ import annotations

from datetime import date, datetime

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.orm import Session

from app.clock import utc_now
from app.db import get_db
from app.schemas import digests as schemas
from app.services import digests as service

router = APIRouter(prefix="/digests", tags=["digests"])


@router.post("", response_model=schemas.DigestOut)
def create_digest(
    body: schemas.DigestCreate,
    response: Response,
    db: Session = Depends(get_db),
    now: datetime = Depends(utc_now),
) -> schemas.DigestOut:
    """Create (201) or regenerate (200) the digest of the period containing ``date``."""
    digest, created = service.generate(db, body.kind, body.date, now)
    response.status_code = status.HTTP_201_CREATED if created else status.HTTP_200_OK
    return digest


@router.get("", response_model=schemas.DigestList)
def list_digests(
    kind: schemas.DigestKindIn | None = None,
    db: Session = Depends(get_db),
    now: datetime = Depends(utc_now),
) -> schemas.DigestList:
    return service.list_digests(db, kind, now)


# Static paths before "/{digest_id}" so they are not read as an id.
@router.get("/suggestion", response_model=schemas.DigestSuggestion)
def get_suggestion(
    db: Session = Depends(get_db), now: datetime = Depends(utc_now)
) -> schemas.DigestSuggestion:
    return service.suggestion(db, now)


@router.get("/by-period", response_model=schemas.DigestOut)
def get_by_period(
    kind: schemas.DigestKindIn, date: date, db: Session = Depends(get_db)
) -> schemas.DigestOut:
    return service.get_by_period(db, kind, date)


@router.get("/{digest_id}", response_model=schemas.DigestOut)
def get_digest(digest_id: int, db: Session = Depends(get_db)) -> schemas.DigestOut:
    return service.get(db, digest_id)


@router.patch("/{digest_id}", response_model=schemas.DigestOut)
def patch_digest(
    digest_id: int,
    body: schemas.DigestPatch,
    db: Session = Depends(get_db),
    now: datetime = Depends(utc_now),
) -> schemas.DigestOut:
    return service.update_review(db, digest_id, body, now)

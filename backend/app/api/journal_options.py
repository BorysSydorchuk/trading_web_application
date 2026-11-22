"""/api/journal-options/{field}: the owner's editable choice lists (Settings «Емоції»)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.orm import Session

from app.db import get_db
from app.schemas import journal_options as schemas
from app.services import journal_options as service

router = APIRouter(prefix="/journal-options")


def _out(view: service.OptionView) -> schemas.OptionOut:
    return schemas.OptionOut(
        value=view.value,
        label=view.label,
        hidden=view.hidden,
        synonyms=list(view.synonyms),
        used_count=view.used_count,
    )


def _list(field: str, views: list[service.OptionView]) -> schemas.OptionList:
    return schemas.OptionList(field=field, options=[_out(v) for v in views])


@router.get("/{field}", response_model=schemas.OptionList)
def list_options(field: str, db: Session = Depends(get_db)) -> schemas.OptionList:
    return _list(field, service.list_options(db, field))


@router.post("/{field}", response_model=schemas.OptionOut, status_code=status.HTTP_201_CREATED)
def add_option(
    field: str, body: schemas.OptionCreate, db: Session = Depends(get_db)
) -> schemas.OptionOut:
    return _out(service.add_option(db, field, body.label, body.synonyms))


@router.put("/{field}/order", response_model=schemas.OptionList)
def reorder_options(
    field: str, body: schemas.OptionOrder, db: Session = Depends(get_db)
) -> schemas.OptionList:
    return _list(field, service.reorder_options(db, field, body.values))


@router.patch("/{field}/{value}", response_model=schemas.OptionOut)
def update_option(
    field: str, value: str, body: schemas.OptionUpdate, db: Session = Depends(get_db)
) -> schemas.OptionOut:
    view = service.update_option(
        db, field, value, label=body.label, hidden=body.hidden, synonyms=body.synonyms
    )
    return _out(view)


@router.delete("/{field}/{value}", status_code=status.HTTP_204_NO_CONTENT)
def delete_option(field: str, value: str, db: Session = Depends(get_db)) -> Response:
    service.delete_option(db, field, value)
    return Response(status_code=status.HTTP_204_NO_CONTENT)

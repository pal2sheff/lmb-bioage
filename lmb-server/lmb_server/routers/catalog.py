"""Справочники для интерфейса."""
from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..catalog import ui_catalog
from ..db import get_db
from ..deps import Principal, require
from ..models import ObservationDefinition

router = APIRouter(tags=["catalog"])


@router.get("/catalog")
def catalog(p: Principal = Depends(require("doctor")), db: Session = Depends(get_db)):
    defs = [{"code": d.code, "name_ru": d.name_ru, "unit_canonical": d.unit_canonical,
             "allowed_units": d.allowed_units, "plausible_min": d.plausible_min, "plausible_max": d.plausible_max}
            for d in db.scalars(select(ObservationDefinition))]
    return ui_catalog(defs)

"""`/promo/v0` — promotion display identifier minting.

The builder UI of the imitated platform pre-allocates one display id per
promotion activity before posting the draft; drafts posted with blank ids
get them re-minted server-side during create.
"""
from __future__ import annotations

from fastapi import APIRouter, Body, Depends
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_session
from ..ids import mint_promotion_display_id
from ..models import PromotionDisplayId

router = APIRouter(prefix="/promo/v0", tags=["promo"])


@router.post("/promotion-display-identifier")
def mint_display_identifier(
    payload: dict = Body(default={}), session: Session = Depends(get_session)
):
    brand = payload.get("brand") or settings.default_brand
    display_id = mint_promotion_display_id(session)
    session.add(PromotionDisplayId(display_id=display_id, brand=brand))
    return {"promotionDisplayId": display_id}

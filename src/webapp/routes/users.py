from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from starlette import status

from src.amocrm.client import amocrm
from src.database.crud import get_user
from src.database import get_db

router = APIRouter(prefix="/users", tags=["users"])

@router.get("")
async def get_users(column_name: str = Query(..., description="Column name to filter by"), value: str = Query(..., description="Value for the column"), db: AsyncSession = Depends(get_db)):
    if column_name in ["tg_id"]:
        user = await get_user(db, column_name, value)
        if not user:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
        data = user.to_dict()
        data.update({"name": "", "surname": "", "email": "", "phone": ""})
        if user.contact_id:
            try:
                contact = await amocrm.get_contact(int(user.contact_id))
            except Exception:
                contact = None
            data.update(amocrm.contact_payload(contact))
        return data

    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)

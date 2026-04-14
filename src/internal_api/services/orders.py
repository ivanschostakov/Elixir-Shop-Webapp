import aiosmtplib
from sqlalchemy.ext.asyncio import AsyncSession

from src.amocrm.client import amocrm
from src.internal_api.schemas import InternalVerifyOrderOut
from src.webapp.schemas.webhooks import VerifyOrderOut


async def verify_order_code_service(db: AsyncSession, code: str | int) -> VerifyOrderOut:
    del db
    try:
        price, email, verification_code = await amocrm.get_valid_deal_price_and_email_verification_code_for_ai(code)
    except (aiosmtplib.errors.SMTPException, OSError, TimeoutError):
        return InternalVerifyOrderOut(status="smtp_failed", price="not_found", email=None, verification_code=None)

    if price == "not_found":
        return InternalVerifyOrderOut(status="not_found", price="not_found", email=None, verification_code=None)
    if price == "low":
        return InternalVerifyOrderOut(status="low", price="low", email=None, verification_code=None)
    if not email or not verification_code:
        return InternalVerifyOrderOut(status="no_email", price=price, email=email, verification_code=None)
    return InternalVerifyOrderOut(status="ok", price=price, email=email, verification_code=verification_code)

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from src.database.schemas import BotLiteral, LastUsedLiteral
from src.webapp.schemas.webhooks import VerifyOrderIn, VerifyOrderOut


class InternalErrorPayload(BaseModel):
    code: str
    message: str
    details: Any | None = None


class InternalErrorEnvelope(BaseModel):
    error: InternalErrorPayload
    request_id: str


class InternalUserRead(BaseModel):
    model_config = ConfigDict(extra="allow")

    tg_id: int
    tg_ref_id: int | None = None
    tg_phone: str | None = None
    photo_url: str | None = None
    contact_id: int | None = None
    moysklad_counterparty_id: str | None = None
    premium_requests: float = 0
    premium_until: datetime | None = None
    conversation_id: str | None = None
    last_used: LastUsedLiteral = "professor"
    input_tokens: int = 0
    output_tokens: int = 0
    blocked_until: datetime | None = None
    utm_source: str | None = None
    utm_medium: str | None = None
    utm_campaign: str | None = None
    utm_content: str | None = None
    utm_creative: str | None = None
    utm_payload_raw: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    name: str = ""
    surname: str = ""
    full_name: str = ""
    email: str = ""
    phone: str = ""
    contact_info: str = ""


class InternalFeatureRead(BaseModel):
    onec_id: str
    product_onec_id: str
    name: str
    code: str
    file_id: str | None = None
    price: Decimal
    balance: int


class InternalProductRead(BaseModel):
    id: int
    onec_id: str
    name: str
    code: str
    description: str | None = None
    usage: str | None = None
    expiration: str | None = None
    category_onec_id: str | None = None
    features: list[InternalFeatureRead] = Field(default_factory=list)


class InternalUsedCodeRead(BaseModel):
    id: int
    user_id: int
    code: str
    price: Decimal


class InternalPromoRead(BaseModel):
    id: int
    code: str
    discount_pct: Decimal
    owner_name: str
    owner_pct: Decimal
    owner_amount_gained: Decimal
    lvl1_name: str | None = None
    lvl1_pct: Decimal
    lvl1_amount_gained: Decimal
    lvl2_name: str | None = None
    lvl2_pct: Decimal
    lvl2_amount_gained: Decimal
    times_used: int
    created_at: datetime
    updated_at: datetime


class InternalCartRead(BaseModel):
    id: int
    user_id: int
    name: str | None = None
    phone: str
    email: str
    sum: Decimal
    delivery_sum: Decimal
    promo_code: str | None = None
    promo_gains: Decimal
    promo_gains_given: bool
    delivery_string: str
    commentary: str | None = None
    payment_method: str | None = None
    payment_provider: str | None = None
    payment_status: str | None = None
    payment_invoice_id: str | None = None
    payment_paid_at: datetime | None = None
    amocrm_lead_id: int | None = None
    moysklad_customerorder_id: str | None = None
    moysklad_invoiceout_id: str | None = None
    delivery_created_at: datetime | None = None
    delivery_provider_ref: str | None = None
    is_active: bool
    is_paid: bool
    is_canceled: bool
    is_shipped: bool
    status: str | None = None
    yandex_request_id: str | None = None
    created_at: datetime
    updated_at: datetime
    user: InternalUserRead | None = None


class InternalLookupUserIn(BaseModel):
    column_name: str
    raw_value: Any


class InternalSearchUsersIn(BaseModel):
    by: str
    value: Any
    page: int | None = None
    limit: int | None = None


class InternalUpdateUserNameIn(BaseModel):
    first_name: str | None = None
    last_name: str | None = None


class InternalIncrementTokensIn(BaseModel):
    tg_id: int
    input_inc: int = 0
    output_inc: int = 0


class InternalWriteUsageIn(BaseModel):
    user_id: int
    input_tokens: int
    output_tokens: int
    bot: BotLiteral
    usage_date: date | None = None
    cached_input_tokens: int | None = None


class InternalGetTotalRequestsIn(BaseModel):
    user_id: int
    bots: list[BotLiteral] | None = None


class InternalGetUsagesIn(BaseModel):
    start_date: date
    end_date: date | None = None
    bot: BotLiteral | None = None


class InternalGetUserUsageTotalsIn(BaseModel):
    user_id: int
    start_date: date | None = None
    end_date: date | None = None


class InternalUtmFunnelReportIn(BaseModel):
    start_date: date
    end_date: date


class InternalGetCartsIn(BaseModel):
    exclude_starting: bool = True


class InternalGetUserCartsIn(BaseModel):
    user_id: int
    is_active: bool | None = None
    exclude_starting: bool = True


class InternalGetCartsByDateIn(BaseModel):
    dt: datetime


class InternalSearchCartsIn(BaseModel):
    value: Any
    page: int | None = None
    limit: int | None = None


class InternalUserCartsAnalyticsIn(BaseModel):
    user_id: int
    days: int = 30
    top_n: int = 5
    recent_n: int = 8


class InternalCartAnalysisIn(BaseModel):
    cart_id: int


class InternalBooleanResult(BaseModel):
    ok: bool


class InternalIdResult(BaseModel):
    id: int


class InternalTotalRequestsOut(BaseModel):
    total_requests: int


class InternalUsageReportOut(BaseModel):
    period_label: str
    usages: list[dict[str, Any]]


class InternalUserUsageTotalsOut(BaseModel):
    period: str
    user_id: int
    tg_phone: str | None = None
    by_bot: list[dict[str, Any]]
    totals: dict[str, Any]


class InternalUtmFunnelRow(BaseModel):
    utm_source: str | None = None
    utm_medium: str | None = None
    utm_campaign: str | None = None
    utm_content: str | None = None
    utm_creative: str | None = None
    registrations: int = 0
    verified_users: int = 0
    paid_users: int = 0
    paid_orders: int = 0
    goods_revenue: float = 0.0
    delivery_revenue: float = 0.0
    total_revenue: float = 0.0
    ai_total_requests: int = 0
    input_tokens: int = 0
    cached_input_tokens: int = 0
    output_tokens: int = 0
    ai_total_cost_usd: float = 0.0


class InternalUtmFunnelUser(BaseModel):
    tg_id: int
    tg_phone: str | None = None
    created_at: datetime
    updated_at: datetime
    utm_source: str | None = None
    utm_medium: str | None = None
    utm_campaign: str | None = None
    utm_content: str | None = None
    utm_creative: str | None = None
    utm_payload_raw: str | None = None
    verified: bool = False
    paid_orders: int = 0
    goods_revenue: float = 0.0
    delivery_revenue: float = 0.0
    total_revenue: float = 0.0
    ai_total_requests: int = 0
    input_tokens: int = 0
    cached_input_tokens: int = 0
    output_tokens: int = 0
    ai_total_cost_usd: float = 0.0


class InternalUtmFunnelReportOut(BaseModel):
    period_label: str
    rows: list[InternalUtmFunnelRow]
    users: list[InternalUtmFunnelUser]


class InternalSearchUsersOut(BaseModel):
    rows: list[InternalUserRead]
    total: int


class InternalSearchCartsOut(BaseModel):
    rows: list[InternalCartRead]
    total: int


class InternalTextOut(BaseModel):
    text: str


class InternalVerifyOrderOut(VerifyOrderOut):
    pass


class InternalVerifyOrderIn(VerifyOrderIn):
    pass

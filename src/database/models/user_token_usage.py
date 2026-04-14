from datetime import date as dt_date
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from enum import Enum
from sqlalchemy import BigInteger, Boolean, Date, Enum as SAEnum, Float, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship, validates

from src.database import Base


class BotEnum(str, Enum):
    dose = "dose"
    professor = "professor"
    new = "new"


@dataclass(frozen=True)
class ModelPricing:
    model: str
    input_per_million_usd: Decimal
    cached_input_per_million_usd: Decimal
    output_per_million_usd: Decimal
    cached_ratio_base: Decimal
    cached_ratio_per_extra_request: Decimal
    cached_ratio_cap: Decimal


class UserTokenUsage(Base):
    __tablename__ = "user_token_usage"
    __table_args__ = (UniqueConstraint("user_id", "date", "bot", name="uq_user_date_bot"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.tg_id", ondelete="CASCADE"), index=True)
    date: Mapped[dt_date] = mapped_column(Date, index=True, default=dt_date.today)
    input_tokens: Mapped[int] = mapped_column(BigInteger, default=0)
    cached_input_tokens: Mapped[int] = mapped_column(BigInteger, default=0)
    cached_input_tokens_estimated: Mapped[bool] = mapped_column(Boolean, default=False)
    output_tokens: Mapped[int] = mapped_column(BigInteger, default=0)
    input_cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    output_cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    total_requests: Mapped[int] = mapped_column(BigInteger, default=0)
    bot: Mapped[BotEnum] = mapped_column(SAEnum(BotEnum, name="bot_enum"), index=True, nullable=False)

    user: Mapped["User"] = relationship("User", back_populates="token_usage")

    USD_QUANT = Decimal("0.000001")
    TOKENS_PER_MILLION = Decimal("1000000")
    # Official source: https://openai.com/api/pricing/
    BOT_PRICING = {
        # Legacy backfill heuristic only:
        # - used for historical rows created before exact cached token counts were stored
        # - no live pricing path should depend on this ratio once cached_input_tokens is present
        BotEnum.dose: ModelPricing("gpt-5-mini", Decimal("0.25"), Decimal("0.025"), Decimal("2.00"), Decimal("0.15"), Decimal("0.06"), Decimal("0.45")),
        BotEnum.professor: ModelPricing("gpt-5-mini", Decimal("0.25"), Decimal("0.025"), Decimal("2.00"), Decimal("0.15"), Decimal("0.06"), Decimal("0.45")),
        BotEnum.new: ModelPricing("gpt-5.4", Decimal("2.50"), Decimal("0.25"), Decimal("15.00"), Decimal("0.25"), Decimal("0.08"), Decimal("0.65")),
    }

    @classmethod
    def get_pricing(cls, bot: BotEnum | str | None) -> ModelPricing | None:
        if bot is None: return None
        if not isinstance(bot, BotEnum): bot = BotEnum(str(bot))
        return cls.BOT_PRICING[bot]

    @classmethod
    def estimate_cached_ratio(cls, bot: BotEnum | str | None, total_requests: int = 1) -> Decimal:
        pricing = cls.get_pricing(bot)
        if pricing is None: return Decimal("0")

        normalized_requests = max(int(total_requests or 0), 1)
        extra_requests = Decimal(normalized_requests - 1)
        estimated_ratio = pricing.cached_ratio_base + pricing.cached_ratio_per_extra_request * extra_requests
        return min(pricing.cached_ratio_cap, estimated_ratio)

    @classmethod
    def estimate_cached_input_tokens(cls, bot: BotEnum | str | None, input_tokens: int = 0, total_requests: int = 1) -> int:
        total_input_tokens = Decimal(max(int(input_tokens or 0), 0))
        estimated_cached_tokens = (total_input_tokens * cls.estimate_cached_ratio(bot, total_requests)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        return min(int(total_input_tokens), max(int(estimated_cached_tokens), 0))

    @classmethod
    def calculate_costs(
            cls,
            bot: BotEnum | str | None,
            input_tokens: int = 0,
            cached_input_tokens: int = 0,
            output_tokens: int = 0,
    ) -> tuple[float, float]:
        pricing = cls.get_pricing(bot)
        if pricing is None: return 0.0, 0.0

        total_input_tokens = Decimal(max(int(input_tokens or 0), 0))
        cached_tokens = Decimal(min(max(int(cached_input_tokens or 0), 0), int(total_input_tokens)))
        fresh_input_tokens = total_input_tokens - cached_tokens
        input_cost = ((fresh_input_tokens * pricing.input_per_million_usd) + (cached_tokens * pricing.cached_input_per_million_usd)) / cls.TOKENS_PER_MILLION
        input_cost = input_cost.quantize(cls.USD_QUANT, rounding=ROUND_HALF_UP)
        output_cost = (Decimal(max(int(output_tokens or 0), 0)) * pricing.output_per_million_usd / cls.TOKENS_PER_MILLION).quantize(cls.USD_QUANT, rounding=ROUND_HALF_UP)
        return float(input_cost), float(output_cost)

    @validates("bot", "input_tokens", "cached_input_tokens", "output_tokens")
    def _sync_costs(self, key: str, value: BotEnum | int) -> BotEnum | int:
        bot = value if key == "bot" else getattr(self, "bot", None)
        input_tokens = value if key == "input_tokens" else getattr(self, "input_tokens", 0)
        cached_input_tokens = value if key == "cached_input_tokens" else getattr(self, "cached_input_tokens", 0)
        output_tokens = value if key == "output_tokens" else getattr(self, "output_tokens", 0)
        self.input_cost_usd, self.output_cost_usd = self.calculate_costs(bot, int(input_tokens or 0), int(cached_input_tokens or 0), int(output_tokens or 0))
        return value

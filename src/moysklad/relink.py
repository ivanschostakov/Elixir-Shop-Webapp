import asyncio
import logging
import re
import shutil
import uuid

from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from config import IMAGES_DIR
from src.database import get_session
from src.database.models import Feature, Product
from src.moysklad.main import MoySkladEnterprise

logger = logging.getLogger(__name__)

_MATCH_TOKEN_RE = re.compile(r"[^0-9a-zа-яё]+", re.IGNORECASE)


@dataclass
class MoySkladInitialRelinkStats:
    dry_run: bool = False
    fetched_products: int = 0
    fetched_variants: int = 0

    matched_products: int = 0
    matched_features: int = 0

    relinked_products: int = 0
    relinked_features: int = 0
    already_relinked_products: int = 0
    already_relinked_features: int = 0

    skipped_products_invalid_external_code: int = 0
    skipped_products_invalid_system_id: int = 0
    skipped_products_missing_local: int = 0
    skipped_products_conflict_mapping: int = 0

    skipped_features_invalid_external_code: int = 0
    skipped_features_invalid_system_id: int = 0
    skipped_features_missing_local: int = 0
    skipped_features_conflict_mapping: int = 0

    images_planned_for_rename: int = 0
    images_renamed: int = 0
    images_missing: int = 0
    image_rename_failures: int = 0
    image_backup_path: str | None = None

    product_mapping: list[dict[str, str]] = field(default_factory=list)
    feature_mapping: list[dict[str, str]] = field(default_factory=list)
    image_renames: list[dict[str, str]] = field(default_factory=list)
    images_missing_report: list[dict[str, str]] = field(default_factory=list)
    image_rename_failures_report: list[dict[str, str]] = field(default_factory=list)

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def _uuid_text(value: Any) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    if not normalized:
        return None
    try:
        return str(uuid.UUID(normalized))
    except Exception:
        return None


def _normalized_match_text(value: Any) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    if not normalized:
        return None
    normalized = normalized.casefold().replace("ё", "е")
    normalized = _MATCH_TOKEN_RE.sub(" ", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized or None


def _without_prefix(value: str | None, prefix: str | None) -> str | None:
    if not value or not prefix:
        return value
    if value == prefix:
        return value
    if value.startswith(f"{prefix} "):
        stripped = value[len(prefix) + 1 :].strip()
        return stripped or value
    return value


def _match_keys_from_text(value: Any, *, product_name: Any = None) -> set[str]:
    key = _normalized_match_text(value)
    if key is None:
        return set()
    product_key = _normalized_match_text(product_name)
    keys = {key}
    stripped = _without_prefix(key, product_key)
    if stripped:
        keys.add(stripped)
    return keys


def _variant_characteristic_keys(variant: dict[str, Any]) -> set[str]:
    characteristics = variant.get("characteristics")
    if not isinstance(characteristics, list):
        return set()

    values: list[str] = []
    named_values: list[str] = []

    for item in characteristics:
        if not isinstance(item, dict):
            continue
        name = _normalized_match_text(item.get("name"))
        value = _normalized_match_text(item.get("value"))
        if value:
            values.append(value)
        if name and value:
            named_values.append(f"{name} {value}")
        elif name:
            named_values.append(name)

    keys: set[str] = set()
    if values:
        keys.add(" ".join(values))
        keys.add(" ".join(sorted(values)))
    if named_values:
        keys.add(" ".join(named_values))
        keys.add(" ".join(sorted(named_values)))

    return {key for key in keys if key}


def _moysklad_variant_match_keys(variant: dict[str, Any], *, product_name: Any = None) -> set[str]:
    keys = _match_keys_from_text(variant.get("name"), product_name=product_name)
    keys.update(_variant_characteristic_keys(variant))
    code_key = _normalized_match_text(variant.get("code"))
    if code_key:
        keys.add(code_key)
    return keys


def _local_feature_match_keys(feature: Feature, *, product_name: Any = None) -> set[str]:
    keys = _match_keys_from_text(feature.name, product_name=product_name)
    code_key = _normalized_match_text(feature.code)
    if code_key:
        keys.add(code_key)
    return keys


def _image_report_item(kind: str, old_id: str, new_id: str, source: Path, target: Path, *, error: str | None = None) -> dict[str, str]:
    item = {
        "kind": kind,
        "old_id": old_id,
        "new_id": new_id,
        "source": str(source),
        "target": str(target),
    }
    if error:
        item["error"] = error
    return item


def _rollback_image_renames(image_renames: list[dict[str, str]]) -> None:
    for item in reversed(image_renames):
        source = Path(item["source"])
        target = Path(item["target"])
        if not target.exists() or source.exists():
            continue
        target.rename(source)
        logger.warning("Rolled back image rename target=%s source=%s", target, source)


class MoySkladInitialRelinker:
    def __init__(self, client: MoySkladEnterprise | None = None) -> None:
        self.client = client or MoySkladEnterprise()

    async def run(self, *, dry_run: bool = False) -> MoySkladInitialRelinkStats:
        products, variants = await self._fetch_source_catalog()
        stats = MoySkladInitialRelinkStats(
            dry_run=dry_run,
            fetched_products=len(products),
            fetched_variants=len(variants),
        )

        async with get_session() as session:
            local_products, local_features = await self._load_local_catalog(session)
            product_mapping = self._build_product_mapping(products, local_products, stats)
            feature_mapping = self._build_feature_mapping(
                variants=variants,
                local_products=local_products,
                local_features=local_features,
                product_mapping=product_mapping,
                stats=stats,
            )

            stats.product_mapping = [
                {"old_id": old_id, "new_id": new_id}
                for old_id, new_id in sorted(product_mapping.items())
                if old_id != new_id
            ]
            stats.feature_mapping = [
                {"old_id": old_id, "new_id": new_id}
                for old_id, new_id in sorted(feature_mapping.items())
                if old_id != new_id
            ]

            image_plans = self._plan_image_renames(product_mapping, feature_mapping, stats)
            stats.images_planned_for_rename = len(image_plans)

            if dry_run:
                stats.image_renames.extend(item for _, _, item in image_plans)
                await session.rollback()
                return stats

            if image_plans:
                self._backup_images(stats)

            self._execute_image_rename_plans(image_plans, stats=stats)

            try:
                await self._apply_product_mapping(session, product_mapping, local_products)
                await self._apply_feature_mapping(session, feature_mapping, product_mapping, local_features)
                await self._deduplicate_cart_items(session)
                await session.commit()
            except Exception:
                _rollback_image_renames(stats.image_renames)
                await session.rollback()
                raise

            return stats

    async def _fetch_source_catalog(self) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        if not self.client.is_configured():
            raise RuntimeError("MoySklad integration is not configured")
        products, variants = await asyncio.gather(
            self.client.get_products(),
            self.client.get_variants(),
        )
        return products, variants

    @staticmethod
    async def _load_local_catalog(session: AsyncSession) -> tuple[dict[str, Product], dict[str, Feature]]:
        local_products = list((await session.execute(select(Product))).scalars().all())
        local_features = list((await session.execute(select(Feature))).scalars().all())
        return (
            {product.onec_id: product for product in local_products if product.onec_id},
            {feature.onec_id: feature for feature in local_features if feature.onec_id},
        )

    @staticmethod
    def _build_product_mapping(
        products: list[dict[str, Any]],
        local_products: dict[str, Product],
        stats: MoySkladInitialRelinkStats,
    ) -> dict[str, str]:
        mapping: dict[str, str] = {}

        for product in products:
            old_id = _uuid_text(product.get("externalCode"))
            if old_id is None:
                stats.skipped_products_invalid_external_code += 1
                continue

            new_id = _uuid_text(product.get("id"))
            if new_id is None:
                stats.skipped_products_invalid_system_id += 1
                continue

            existing_new = mapping.get(old_id)
            if existing_new is not None and existing_new != new_id:
                stats.skipped_products_conflict_mapping += 1
                continue
            if existing_new == new_id:
                continue

            if old_id not in local_products and new_id not in local_products:
                stats.skipped_products_missing_local += 1
                continue

            mapping[old_id] = new_id
            stats.matched_products += 1

            if old_id == new_id or old_id not in local_products:
                stats.already_relinked_products += 1
            else:
                stats.relinked_products += 1

        return mapping

    def _build_feature_mapping(
        self,
        *,
        variants: list[dict[str, Any]],
        local_products: dict[str, Product],
        local_features: dict[str, Feature],
        product_mapping: dict[str, str],
        stats: MoySkladInitialRelinkStats,
    ) -> dict[str, str]:
        mapping: dict[str, str] = {}

        for variant in variants:
            new_id = _uuid_text(variant.get("id"))
            if new_id is None:
                stats.skipped_features_invalid_system_id += 1
                continue

            old_id = _uuid_text(variant.get("externalCode"))
            if old_id is not None:
                self._register_feature_mapping(
                    mapping,
                    old_id=old_id,
                    new_id=new_id,
                    local_features=local_features,
                    stats=stats,
                )
                continue

            if self._try_match_feature_by_name(
                mapping=mapping,
                variant=variant,
                new_id=new_id,
                local_products=local_products,
                local_features=local_features,
                product_mapping=product_mapping,
                stats=stats,
            ):
                continue

            stats.skipped_features_invalid_external_code += 1

        # Synthetic feature mapping for products without real variants.
        for old_product_id, new_product_id in product_mapping.items():
            old_feature_id = f"{old_product_id}__synthetic"
            new_feature_id = f"{new_product_id}__synthetic"
            if old_feature_id not in local_features and new_feature_id not in local_features:
                continue
            self._register_feature_mapping(
                mapping,
                old_id=old_feature_id,
                new_id=new_feature_id,
                local_features=local_features,
                stats=stats,
            )

        return mapping

    def _try_match_feature_by_name(
        self,
        *,
        mapping: dict[str, str],
        variant: dict[str, Any],
        new_id: str,
        local_products: dict[str, Product],
        local_features: dict[str, Feature],
        product_mapping: dict[str, str],
        stats: MoySkladInitialRelinkStats,
    ) -> bool:
        product_meta = variant.get("product") if isinstance(variant.get("product"), dict) else {}
        old_product_id = _uuid_text(product_meta.get("externalCode"))
        if old_product_id is None:
            old_product_id = _uuid_text(variant.get("externalCode"))

        if old_product_id is None:
            return False

        local_product = local_products.get(old_product_id)
        if local_product is None:
            mapped_product_id = product_mapping.get(old_product_id)
            if mapped_product_id:
                local_product = local_products.get(mapped_product_id)
        if local_product is None:
            return False

        local_features_for_product = [
            feature
            for feature in local_features.values()
            if feature.product_onec_id == local_product.onec_id
        ]
        if not local_features_for_product:
            return False

        variant_keys = _moysklad_variant_match_keys(variant, product_name=local_product.name)
        if not variant_keys:
            return False

        candidates: list[Feature] = []
        for feature in local_features_for_product:
            local_keys = _local_feature_match_keys(feature, product_name=local_product.name)
            if variant_keys.intersection(local_keys):
                candidates.append(feature)

        if len(candidates) != 1:
            return False

        candidate = candidates[0]
        self._register_feature_mapping(
            mapping,
            old_id=candidate.onec_id,
            new_id=new_id,
            local_features=local_features,
            stats=stats,
            matched_by_name=True,
            variant_payload=variant,
        )
        return True

    @staticmethod
    def _register_feature_mapping(
        mapping: dict[str, str],
        *,
        old_id: str,
        new_id: str,
        local_features: dict[str, Feature],
        stats: MoySkladInitialRelinkStats,
        matched_by_name: bool = False,
        variant_payload: dict[str, Any] | None = None,
    ) -> None:
        existing_new = mapping.get(old_id)
        if existing_new is not None and existing_new != new_id:
            stats.skipped_features_conflict_mapping += 1
            return
        if existing_new == new_id:
            return

        if old_id not in local_features and new_id not in local_features:
            stats.skipped_features_missing_local += 1
            return

        if matched_by_name:
            logger.info(
                "Feature matched by name old_id=%s new_id=%s variant_name=%s",
                old_id,
                new_id,
                (variant_payload or {}).get("name"),
            )

        mapping[old_id] = new_id
        stats.matched_features += 1

        if old_id == new_id or old_id not in local_features:
            stats.already_relinked_features += 1
        else:
            stats.relinked_features += 1

    @staticmethod
    def _plan_image_renames(
        product_mapping: dict[str, str],
        feature_mapping: dict[str, str],
        stats: MoySkladInitialRelinkStats,
    ) -> list[tuple[Path, Path, dict[str, str]]]:
        plans: list[tuple[Path, Path, dict[str, str]]] = []

        for kind, mapping in (("product", product_mapping), ("feature", feature_mapping)):
            for old_id, new_id in mapping.items():
                if old_id == new_id:
                    continue

                source = IMAGES_DIR / f"{old_id}.png"
                target = IMAGES_DIR / f"{new_id}.png"
                item = _image_report_item(kind, old_id, new_id, source, target)

                if not source.exists():
                    stats.images_missing += 1
                    stats.images_missing_report.append(item)
                    continue

                if target.exists():
                    # Existing target image is treated as an already migrated or manually uploaded file.
                    continue

                plans.append((source, target, item))

        # Ensure one target path is not planned more than once.
        seen_targets: set[Path] = set()
        unique_plans: list[tuple[Path, Path, dict[str, str]]] = []
        for source, target, item in plans:
            if target in seen_targets:
                stats.image_rename_failures += 1
                failure = {**item, "error": "duplicate_target"}
                stats.image_rename_failures_report.append(failure)
                continue
            seen_targets.add(target)
            unique_plans.append((source, target, item))

        return unique_plans

    @staticmethod
    def _backup_images(stats: MoySkladInitialRelinkStats) -> None:
        backup_root = IMAGES_DIR.parent / "image-backups"
        timestamp = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
        backup_path = backup_root / f"moysklad-initial-relink-{timestamp}"
        suffix = 1
        while backup_path.exists():
            suffix += 1
            backup_path = backup_root / f"moysklad-initial-relink-{timestamp}-{suffix}"

        backup_root.mkdir(parents=True, exist_ok=True)
        shutil.copytree(IMAGES_DIR, backup_path)
        stats.image_backup_path = str(backup_path)

    @staticmethod
    def _execute_image_rename_plans(
        plans: list[tuple[Path, Path, dict[str, str]]],
        *,
        stats: MoySkladInitialRelinkStats,
    ) -> None:
        for source, target, item in plans:
            try:
                target.parent.mkdir(parents=True, exist_ok=True)
                source.rename(target)
            except Exception as exc:
                stats.image_rename_failures += 1
                failure = {**item, "error": str(exc)}
                stats.image_rename_failures_report.append(failure)
                _rollback_image_renames(stats.image_renames)
                raise

            stats.images_renamed += 1
            stats.image_renames.append(item)

    @staticmethod
    async def _apply_product_mapping(
        session: AsyncSession,
        product_mapping: dict[str, str],
        local_products: dict[str, Product],
    ) -> None:
        for old_id, new_id in product_mapping.items():
            if old_id == new_id:
                continue

            old_product = local_products.get(old_id)
            if old_product is None:
                continue

            await session.execute(
                text(
                    """
                    INSERT INTO products (onec_id, name, code, description, usage, expiration, category_onec_id)
                    SELECT :new_id, p.name, p.code, p.description, p.usage, p.expiration, p.category_onec_id
                    FROM products p
                    WHERE p.onec_id = :old_id
                    ON CONFLICT (onec_id) DO NOTHING
                    """
                ),
                {"old_id": old_id, "new_id": new_id},
            )

            await session.execute(
                text(
                    """
                    INSERT INTO product_tg_categories (product_onec_id, tg_category_id)
                    SELECT :new_id, ptc.tg_category_id
                    FROM product_tg_categories ptc
                    WHERE ptc.product_onec_id = :old_id
                    ON CONFLICT (product_onec_id, tg_category_id) DO NOTHING
                    """
                ),
                {"old_id": old_id, "new_id": new_id},
            )
            await session.execute(
                text("DELETE FROM product_tg_categories WHERE product_onec_id = :old_id"),
                {"old_id": old_id},
            )

            await session.execute(
                text(
                    """
                    INSERT INTO favourites (user_id, onec_id)
                    SELECT f.user_id, :new_id
                    FROM favourites f
                    WHERE f.onec_id = :old_id
                    ON CONFLICT ON CONSTRAINT uq_favourites_user_product DO NOTHING
                    """
                ),
                {"old_id": old_id, "new_id": new_id},
            )
            await session.execute(text("DELETE FROM favourites WHERE onec_id = :old_id"), {"old_id": old_id})

            await session.execute(
                text("UPDATE features SET product_onec_id = :new_id WHERE product_onec_id = :old_id"),
                {"old_id": old_id, "new_id": new_id},
            )
            await session.execute(
                text("UPDATE cart_items SET product_onec_id = :new_id WHERE product_onec_id = :old_id"),
                {"old_id": old_id, "new_id": new_id},
            )

            local_products[new_id] = old_product
            del local_products[old_id]

        # Delete old products only after references have been moved.
        for old_id, new_id in product_mapping.items():
            if old_id == new_id:
                continue
            await session.execute(text("DELETE FROM products WHERE onec_id = :old_id"), {"old_id": old_id})

    @staticmethod
    async def _apply_feature_mapping(
        session: AsyncSession,
        feature_mapping: dict[str, str],
        product_mapping: dict[str, str],
        local_features: dict[str, Feature],
    ) -> None:
        for old_id, new_id in feature_mapping.items():
            if old_id == new_id:
                continue

            old_feature = local_features.get(old_id)
            if old_feature is None:
                continue

            target_product_id = product_mapping.get(old_feature.product_onec_id, old_feature.product_onec_id)
            target_name = old_feature.name

            await session.execute(
                text(
                    """
                    INSERT INTO features (onec_id, product_onec_id, name, code, file_id, price, balance)
                    SELECT :new_id, :target_product_id, :name, f.code, f.file_id, f.price, f.balance
                    FROM features f
                    WHERE f.onec_id = :old_id
                    ON CONFLICT (onec_id) DO NOTHING
                    """
                ),
                {
                    "old_id": old_id,
                    "new_id": new_id,
                    "target_product_id": target_product_id,
                    "name": target_name,
                },
            )

            await session.execute(
                text("UPDATE features SET product_onec_id = :target_product_id WHERE onec_id = :new_id"),
                {"new_id": new_id, "target_product_id": target_product_id},
            )

            await session.execute(
                text(
                    """
                    UPDATE cart_items ci
                    SET feature_onec_id = :new_id
                    WHERE ci.feature_onec_id = :old_id
                    """
                ),
                {"old_id": old_id, "new_id": new_id},
            )

            local_features[new_id] = old_feature
            del local_features[old_id]

        for old_id, new_id in feature_mapping.items():
            if old_id == new_id:
                continue
            await session.execute(text("DELETE FROM features WHERE onec_id = :old_id"), {"old_id": old_id})

    @staticmethod
    async def _deduplicate_cart_items(session: AsyncSession) -> None:
        # Collapse accidental duplicates after relink by merging quantities.
        await session.execute(
            text(
                """
                WITH ranked AS (
                    SELECT
                        id,
                        cart_id,
                        product_onec_id,
                        feature_onec_id,
                        quantity,
                        MIN(id) OVER (PARTITION BY cart_id, product_onec_id, feature_onec_id) AS keep_id
                    FROM cart_items
                ),
                aggregated AS (
                    SELECT keep_id, SUM(quantity)::int AS total_quantity
                    FROM ranked
                    GROUP BY keep_id
                ),
                updated AS (
                    UPDATE cart_items ci
                    SET quantity = aggregated.total_quantity
                    FROM aggregated
                    WHERE ci.id = aggregated.keep_id
                    RETURNING ci.id
                )
                DELETE FROM cart_items ci
                USING ranked
                WHERE ci.id = ranked.id AND ranked.id <> ranked.keep_id
                """
            )
        )


async def run_moysklad_initial_relink(*, dry_run: bool = False) -> MoySkladInitialRelinkStats:
    logger.info("MoySklad initial relink started dry_run=%s", dry_run)
    relinker = MoySkladInitialRelinker()
    try:
        stats = await relinker.run(dry_run=dry_run)
        logger.info("MoySklad initial relink finished stats=%s", stats.as_dict())
        return stats
    finally:
        await relinker.client.close()

"""Configure Langfuse pricing for the image model used by this project."""

import argparse
import re
from datetime import UTC, datetime
from pathlib import Path

from dotenv import load_dotenv
from langfuse import Langfuse
from langfuse.api.commons.types.model_usage_unit import ModelUsageUnit
from langfuse.api.commons.types.pricing_tier_input import PricingTierInput

API_ROOT = Path(__file__).resolve().parents[1]
MODEL_NAME = "gpt-image-2.5-sunburst"
MATCH_PATTERN = r"(?i)^(openai/)?(gpt-image-2\.5-sunburst)$"
PRICING_START = datetime(2026, 10, 17, tzinfo=UTC)

# OpenAI Standard-processing prices per token on 2026-10-17:
# https://developers.openai.com/api/docs/pricing
PRICES_PER_TOKEN = {
    "input_text_tokens": 5.00 / 1_000_000,
    "input_image_tokens": 8.00 / 1_000_000,
    "output_text_tokens": 0.0,
    "output_image_tokens": 30.00 / 1_000_000,
}


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Preview or apply the Langfuse model-price definition required "
            "for gpt-image-2.5-sunburst."
        )
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Create or update the remote model definition.",
    )
    return parser.parse_args()


def _load_all_models(client: Langfuse) -> list:
    first_page = client.api.models.list(page=1, limit=100)
    models = list(first_page.data)
    for page_number in range(2, first_page.meta.total_pages + 1):
        models.extend(
            client.api.models.list(
                page=page_number,
                limit=100,
            ).data
        )
    return models


def _matching_models(models: list) -> list:
    matches = []
    for model in models:
        try:
            pattern_matches = re.search(
                model.match_pattern,
                MODEL_NAME,
            ) is not None
        except re.error:
            pattern_matches = False
        if pattern_matches:
            matches.append(model)
    return matches


def _pricing_tier() -> PricingTierInput:
    return PricingTierInput(
        name="Standard",
        is_default=True,
        priority=0,
        conditions=[],
        prices=PRICES_PER_TOKEN,
    )


def main() -> int:
    args = _parse_args()
    load_dotenv(API_ROOT / ".env", override=True)
    client = Langfuse()
    models = _load_all_models(client)
    matches = _matching_models(models)

    if any(model.is_langfuse_managed for model in matches):
        print(
            {
                "status": "managed_model_already_matches",
                "model_name": MODEL_NAME,
                "matching_models": [model.model_name for model in matches],
            }
        )
        return 0

    exact_custom = next(
        (
            model
            for model in matches
            if model.model_name == MODEL_NAME
            and not model.is_langfuse_managed
        ),
        None,
    )
    action = "update" if exact_custom is not None else "create"
    preview = {
        "status": "preview" if not args.apply else "applying",
        "action": action,
        "model_name": MODEL_NAME,
        "match_pattern": MATCH_PATTERN,
        "pricing_start": PRICING_START.isoformat(),
        "prices_per_token_usd": PRICES_PER_TOKEN,
    }
    print(preview)

    if not args.apply:
        return 0

    common = {
        "model_name": MODEL_NAME,
        "match_pattern": MATCH_PATTERN,
        "unit": ModelUsageUnit.TOKENS,
        "start_date": PRICING_START,
        "input_price": None,
        "output_price": None,
        "total_price": None,
        "pricing_tiers": [_pricing_tier()],
    }
    if exact_custom is None:
        configured = client.api.models.create(**common)
    else:
        configured = client.api.models.upsert(
            exact_custom.id,
            **common,
        )

    print(
        {
            "status": "configured",
            "model_id": configured.id,
            "model_name": configured.model_name,
            "is_langfuse_managed": configured.is_langfuse_managed,
        }
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

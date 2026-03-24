"""Token usage and pricing helpers for LLM span enrichment."""

from __future__ import annotations

from decimal import Decimal


# Prices are USD per token (not per 1K tokens) for direct multiplication.
_MODEL_PRICES: dict[str, dict[str, float]] = {
	"gpt-4.1": {"input": 2.0 / 1_000_000, "output": 8.0 / 1_000_000},
	"gpt-4.1-mini": {"input": 0.4 / 1_000_000, "output": 1.6 / 1_000_000},
	"gpt-4o": {"input": 2.5 / 1_000_000, "output": 10.0 / 1_000_000},
	"gpt-4o-mini": {"input": 0.15 / 1_000_000, "output": 0.6 / 1_000_000},
}


def get_model_price(model: str | None) -> dict[str, float] | None:
	"""Return per-token input/output prices for a model."""
	if not model:
		return None

	model_key = model.strip().lower()
	if model_key in _MODEL_PRICES:
		return _MODEL_PRICES[model_key]

	# Fallback for versioned aliases such as gpt-4.1-mini-2025-xx.
	for known, prices in _MODEL_PRICES.items():
		if model_key.startswith(known):
			return prices

	return None


def _estimate_tokens(text: str | None) -> int | None:
	"""Estimate token count from text when provider token metrics are absent."""
	if text is None:
		return None

	stripped = str(text).strip()
	if not stripped:
		return 0

	# Simple heuristic: ~4 chars per token.
	return max(1, (len(stripped) + 3) // 4)


def calculate_cost(
	model: str | None,
	input_text: str | None,
	output_text: str | None,
) -> dict[str, int | float | None]:
	"""Estimate token usage and cost for a model and input/output payloads."""
	input_tokens = _estimate_tokens(input_text)
	output_tokens = _estimate_tokens(output_text)

	total_tokens = None
	if input_tokens is not None or output_tokens is not None:
		total_tokens = (input_tokens or 0) + (output_tokens or 0)

	cost = None
	prices = get_model_price(model)
	if prices and (input_tokens is not None or output_tokens is not None):
		input_cost = Decimal(input_tokens or 0) * Decimal(str(prices.get("input", 0.0)))
		output_cost = Decimal(output_tokens or 0) * Decimal(str(prices.get("output", 0.0)))
		cost = float(input_cost + output_cost)

	return {
		"input_tokens": input_tokens,
		"output_tokens": output_tokens,
		"total_tokens": total_tokens,
		"cost": cost,
	}


"""Model pricing table and cost calculation."""

# Pricing per million tokens (USD)
MODEL_PRICING = {
    "claude-opus-4-6": {
        "input": 15.00,
        "output": 75.00,
        "cache_read": 1.50,
        "cache_create": 18.75,
    },
    "claude-opus-4-5-20250620": {
        "input": 15.00,
        "output": 75.00,
        "cache_read": 1.50,
        "cache_create": 18.75,
    },
    "claude-sonnet-4-6": {
        "input": 3.00,
        "output": 15.00,
        "cache_read": 0.30,
        "cache_create": 3.75,
    },
    "claude-sonnet-4-5-20250514": {
        "input": 3.00,
        "output": 15.00,
        "cache_read": 0.30,
        "cache_create": 3.75,
    },
    "claude-haiku-4-5-20251001": {
        "input": 0.80,
        "output": 4.00,
        "cache_read": 0.08,
        "cache_create": 1.00,
    },
}

# Default fallback pricing
DEFAULT_PRICING = MODEL_PRICING["claude-sonnet-4-6"]


def estimate_cost(model, input_tokens, output_tokens, cache_read=0, cache_create=0):
    """Calculate estimated cost in USD from token counts."""
    pricing = MODEL_PRICING.get(model, DEFAULT_PRICING)
    cost = (
        input_tokens * pricing["input"] / 1_000_000
        + output_tokens * pricing["output"] / 1_000_000
        + cache_read * pricing["cache_read"] / 1_000_000
        + cache_create * pricing["cache_create"] / 1_000_000
    )
    return round(cost, 4)

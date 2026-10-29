"""Token prices in USD per million tokens.

These are assumptions for the demo. Check https://www.anthropic.com/pricing and update
the table before quoting real costs. Matching is by substring of the model name.
"""

PRICES_PER_MTOK: dict[str, tuple[float, float]] = {
    "opus": (5.00, 25.00),
    "sonnet": (3.00, 15.00),
    "haiku": (1.00, 5.00),
}


def cost_usd(model: str | None, input_tokens: int, output_tokens: int) -> float:
    if not model:
        return 0.0
    for key, (p_in, p_out) in PRICES_PER_MTOK.items():
        if key in model:
            return round((input_tokens * p_in + output_tokens * p_out) / 1_000_000, 6)
    return 0.0

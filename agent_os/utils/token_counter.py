"""
Token Usage and Cost Tracking for Agent_OS

Tracks token usage and calculates costs across different LLM providers.
Essential for budget management and cost optimization.

Features:
- Token usage extraction from LLM responses
- Multi-provider support (OpenAI, Anthropic, Google)
- Up-to-date pricing database
- Cost calculation per call
- Token estimation for prompts
"""

import re
from typing import Dict, Any, Optional, Tuple
from dataclasses import dataclass
from datetime import datetime

from agent_os.utils.logging import get_logger

logger = get_logger(__name__)


# =============================================================================
# Model Pricing Database (as of January 2025)
# =============================================================================

MODEL_PRICING = {
    # OpenAI Models
    "gpt-4o": {"input": 2.50, "output": 10.00},  # per 1M tokens
    "gpt-4o-mini": {"input": 0.15, "output": 0.60},
    "gpt-4-turbo": {"input": 10.00, "output": 30.00},
    "gpt-4-turbo-preview": {"input": 10.00, "output": 30.00},
    "gpt-4": {"input": 30.00, "output": 60.00},
    "gpt-3.5-turbo": {"input": 0.50, "output": 1.50},
    "gpt-3.5-turbo-16k": {"input": 3.00, "output": 4.00},

    # Anthropic Models
    "claude-3-opus-20240229": {"input": 15.00, "output": 75.00},
    "claude-3-sonnet-20240229": {"input": 3.00, "output": 15.00},
    "claude-3-haiku-20240307": {"input": 0.25, "output": 1.25},
    "claude-3-5-sonnet-20240620": {"input": 3.00, "output": 15.00},
    "claude-2.1": {"input": 8.00, "output": 24.00},
    "claude-2": {"input": 8.00, "output": 24.00},
    "claude-instant-1.2": {"input": 0.80, "output": 2.40},

    # Google Models
    "gemini-pro": {"input": 0.50, "output": 1.50},
    "gemini-pro-vision": {"input": 0.50, "output": 1.50},
    "gemini-1.5-pro": {"input": 3.50, "output": 10.50},
    "gemini-1.5-flash": {"input": 0.35, "output": 1.05},

    # Default fallback pricing
    "default": {"input": 1.00, "output": 2.00},
}


def get_model_pricing(model_name: str) -> Dict[str, float]:
    """
    Get pricing for a model

    Args:
        model_name: Model identifier

    Returns:
        Dict with 'input' and 'output' prices per 1M tokens
    """
    # Try exact match first
    if model_name in MODEL_PRICING:
        return MODEL_PRICING[model_name]

    # Try partial match (e.g., "gpt-4o-2024-08-06" matches "gpt-4o")
    model_lower = model_name.lower()
    for key, pricing in MODEL_PRICING.items():
        if key in model_lower or model_lower.startswith(key):
            logger.debug(f"Matched model '{model_name}' to pricing key '{key}'")
            return pricing

    # Fallback to default
    logger.warning(f"No pricing found for model '{model_name}', using default pricing")
    return MODEL_PRICING["default"]


# =============================================================================
# Token Usage Data Classes
# =============================================================================

@dataclass
class TokenUsage:
    """Token usage for a single LLM call"""
    input_tokens: int
    output_tokens: int
    total_tokens: int
    model: str
    timestamp: datetime

    def calculate_cost(self) -> float:
        """Calculate cost based on model pricing"""
        pricing = get_model_pricing(self.model)

        input_cost = (self.input_tokens / 1_000_000) * pricing["input"]
        output_cost = (self.output_tokens / 1_000_000) * pricing["output"]

        return input_cost + output_cost

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.total_tokens,
            "model": self.model,
            "cost": self.calculate_cost(),
            "timestamp": self.timestamp.isoformat()
        }


@dataclass
class CostSummary:
    """Aggregated cost summary"""
    total_calls: int
    total_input_tokens: int
    total_output_tokens: int
    total_tokens: int
    total_cost: float
    model: str
    start_time: datetime
    end_time: datetime

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            "total_calls": self.total_calls,
            "total_input_tokens": self.total_input_tokens,
            "total_output_tokens": self.total_output_tokens,
            "total_tokens": self.total_tokens,
            "total_cost": self.total_cost,
            "average_cost_per_call": self.total_cost / self.total_calls if self.total_calls > 0 else 0,
            "model": self.model,
            "duration_seconds": (self.end_time - self.start_time).total_seconds()
        }


# =============================================================================
# Token Extraction from LLM Responses
# =============================================================================

def extract_token_usage_from_response(response: Any, model: str) -> Optional[TokenUsage]:
    """
    Extract token usage from LLM response

    Supports:
    - OpenAI response format
    - Anthropic response format
    - LangChain response wrappers

    Args:
        response: LLM response object
        model: Model name

    Returns:
        TokenUsage object or None if extraction failed
    """
    try:
        # OpenAI format (direct API or LangChain wrapper)
        if hasattr(response, 'usage'):
            usage = response.usage
            return TokenUsage(
                input_tokens=usage.prompt_tokens,
                output_tokens=usage.completion_tokens,
                total_tokens=usage.total_tokens,
                model=model,
                timestamp=datetime.now()
            )

        # Anthropic format
        if hasattr(response, 'usage') and hasattr(response.usage, 'input_tokens'):
            usage = response.usage
            input_tokens = usage.input_tokens
            output_tokens = usage.output_tokens
            return TokenUsage(
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                total_tokens=input_tokens + output_tokens,
                model=model,
                timestamp=datetime.now()
            )

        # LangChain ChatResult format
        if hasattr(response, 'llm_output') and response.llm_output:
            llm_output = response.llm_output
            if 'token_usage' in llm_output:
                usage = llm_output['token_usage']
                return TokenUsage(
                    input_tokens=usage.get('prompt_tokens', 0),
                    output_tokens=usage.get('completion_tokens', 0),
                    total_tokens=usage.get('total_tokens', 0),
                    model=model,
                    timestamp=datetime.now()
                )

        # LangGraph/StateGraph response with messages
        if isinstance(response, dict) and 'messages' in response:
            # Try to extract from AIMessage response_metadata
            messages = response.get('messages', [])
            if messages and hasattr(messages[-1], 'response_metadata'):
                metadata = messages[-1].response_metadata
                if 'token_usage' in metadata:
                    usage = metadata['token_usage']
                    return TokenUsage(
                        input_tokens=usage.get('prompt_tokens', 0),
                        output_tokens=usage.get('completion_tokens', 0),
                        total_tokens=usage.get('total_tokens', 0),
                        model=model,
                        timestamp=datetime.now()
                    )

        logger.warning(f"Could not extract token usage from response type: {type(response)}")
        return None

    except (AttributeError, KeyError, TypeError, ValueError) as e:
        # Expected errors when response format doesn't match
        logger.error(f"Error extracting token usage: {e}")
        return None
    except Exception as e:
        # Unexpected error - log with full traceback
        logger.exception(f"Unexpected error extracting token usage: {e}")
        return None


def estimate_tokens(text: str) -> int:
    """
    Rough estimation of token count for text

    Uses the approximation: 1 token ≈ 4 characters
    More accurate for English text, less accurate for code/other languages

    Args:
        text: Input text

    Returns:
        Estimated token count
    """
    # Simple estimation: ~4 characters per token
    return len(text) // 4


# =============================================================================
# Cost Estimation
# =============================================================================

def estimate_cost(
    input_text: str,
    output_text: str,
    model: str
) -> Tuple[int, int, float]:
    """
    Estimate cost for a text input/output pair

    Args:
        input_text: Input prompt text
        output_text: Output response text
        model: Model name

    Returns:
        Tuple of (input_tokens, output_tokens, cost)
    """
    input_tokens = estimate_tokens(input_text)
    output_tokens = estimate_tokens(output_text)

    pricing = get_model_pricing(model)
    input_cost = (input_tokens / 1_000_000) * pricing["input"]
    output_cost = (output_tokens / 1_000_000) * pricing["output"]

    return input_tokens, output_tokens, input_cost + output_cost


def calculate_cost(
    input_tokens: int,
    output_tokens: int,
    model: str
) -> float:
    """
    Calculate cost for given token counts

    Args:
        input_tokens: Number of input tokens
        output_tokens: Number of output tokens
        model: Model name

    Returns:
        Total cost in USD
    """
    pricing = get_model_pricing(model)

    input_cost = (input_tokens / 1_000_000) * pricing["input"]
    output_cost = (output_tokens / 1_000_000) * pricing["output"]

    return input_cost + output_cost


# =============================================================================
# Model Cost Comparison
# =============================================================================

def compare_model_costs(
    input_tokens: int,
    output_tokens: int,
    models: list = None
) -> Dict[str, Dict[str, Any]]:
    """
    Compare costs across different models

    Args:
        input_tokens: Number of input tokens
        output_tokens: Number of output tokens
        models: List of model names to compare (defaults to common models)

    Returns:
        Dict mapping model name to cost breakdown
    """
    if models is None:
        models = [
            "gpt-4o",
            "gpt-4o-mini",
            "gpt-3.5-turbo",
            "claude-3-opus-20240229",
            "claude-3-sonnet-20240229",
            "claude-3-haiku-20240307",
            "gemini-pro"
        ]

    comparison = {}

    for model in models:
        cost = calculate_cost(input_tokens, output_tokens, model)
        pricing = get_model_pricing(model)

        comparison[model] = {
            "total_cost": cost,
            "input_cost": (input_tokens / 1_000_000) * pricing["input"],
            "output_cost": (output_tokens / 1_000_000) * pricing["output"],
            "pricing_per_1m": pricing
        }

    return comparison


# =============================================================================
# Pricing Info
# =============================================================================

def get_all_model_pricing() -> Dict[str, Dict[str, float]]:
    """Get pricing for all supported models"""
    return MODEL_PRICING.copy()


def print_pricing_table():
    """Print formatted pricing table"""
    print("\n" + "="*80)
    print("LLM Model Pricing (per 1M tokens)")
    print("="*80)

    providers = {
        "OpenAI": [k for k in MODEL_PRICING.keys() if k.startswith("gpt")],
        "Anthropic": [k for k in MODEL_PRICING.keys() if k.startswith("claude")],
        "Google": [k for k in MODEL_PRICING.keys() if k.startswith("gemini")],
    }

    for provider, models in providers.items():
        if not models:
            continue

        print(f"\n{provider}:")
        print(f"{'Model':<40} {'Input':<12} {'Output':<12}")
        print("-" * 64)

        for model in models:
            pricing = MODEL_PRICING[model]
            print(f"{model:<40} ${pricing['input']:<11.2f} ${pricing['output']:<11.2f}")

    print("="*80 + "\n")

"""Cost Estimator for Multi-Agent Token Consumption."""

from typing import Dict, Any, List, Optional
from config.models_config import calculate_cost, MODEL_PRICING_TABLE
from core.schemas import AgentTokenUsage


class CostEstimator:
    """Calculates granular and aggregate costs across models and agents."""

    def __init__(self, default_model: str = "gemini-2.0-flash"):
        self.default_model = default_model

    def compute_agent_cost(
        self,
        agent_id: str,
        framework: str,
        prompt_tokens: int,
        completion_tokens: int,
        model_name: Optional[str] = None,
    ) -> AgentTokenUsage:
        model = model_name or self.default_model
        cost = calculate_cost(model, prompt_tokens, completion_tokens)
        return AgentTokenUsage(
            agent_id=agent_id,
            framework=framework,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=prompt_tokens + completion_tokens,
            estimated_cost_usd=cost,
        )

    def compute_total_cost(self, agent_usages: List[AgentTokenUsage]) -> float:
        return round(sum(u.estimated_cost_usd for u in agent_usages), 6)


cost_estimator = CostEstimator()

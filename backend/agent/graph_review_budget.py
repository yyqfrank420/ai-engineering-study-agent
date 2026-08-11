"""Request-scoped accounting for graph review calls and corrections."""

from __future__ import annotations

from dataclasses import dataclass

from config import GRAPH_MAX_CONTRACT_CORRECTIONS, GRAPH_MAX_CRITIC_CALLS


class GraphReviewBudgetExceeded(RuntimeError):
    """A graph review provider call would exceed its request-scoped budget."""


@dataclass
class GraphReviewBudget:
    """Charge graph review work at dispatch so cancellation cannot reset it."""

    critic_calls: int = 0
    contract_corrections: int = 0

    def __post_init__(self) -> None:
        if self.critic_calls < 0 or self.contract_corrections < 0:
            raise ValueError("graph review budget counters must be non-negative")

    @property
    def can_claim_correction(self) -> bool:
        return (
            self.critic_calls < GRAPH_MAX_CRITIC_CALLS
            and self.contract_corrections < GRAPH_MAX_CONTRACT_CORRECTIONS
        )

    def claim_provider_call(self, *, correction: bool) -> None:
        if self.critic_calls >= GRAPH_MAX_CRITIC_CALLS:
            raise GraphReviewBudgetExceeded("graph critic provider-call ceiling reached")
        if correction and self.contract_corrections >= GRAPH_MAX_CONTRACT_CORRECTIONS:
            raise GraphReviewBudgetExceeded("graph contract-correction ceiling reached")
        self.critic_calls += 1
        if correction:
            self.contract_corrections += 1

    def state_counters(self) -> dict[str, int]:
        return {
            "graph_critic_call_count": self.critic_calls,
            "graph_contract_correction_count": self.contract_corrections,
        }

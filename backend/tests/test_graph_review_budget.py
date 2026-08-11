import pytest

from agent.graph_review_budget import GraphReviewBudget, GraphReviewBudgetExceeded
from config import GRAPH_MAX_CONTRACT_CORRECTIONS, GRAPH_MAX_CRITIC_CALLS


def test_correction_claim_charges_call_and_correction_together():
    budget = GraphReviewBudget()

    budget.claim_provider_call(correction=False)
    budget.claim_provider_call(correction=True)

    assert budget.critic_calls == 2
    assert budget.contract_corrections == 1
    assert budget.state_counters() == {
        "graph_critic_call_count": 2,
        "graph_contract_correction_count": 1,
    }


def test_provider_call_ceiling_rejects_without_charging_either_counter():
    budget = GraphReviewBudget(
        critic_calls=GRAPH_MAX_CRITIC_CALLS,
        contract_corrections=0,
    )

    with pytest.raises(GraphReviewBudgetExceeded, match="provider-call ceiling"):
        budget.claim_provider_call(correction=True)

    assert budget.critic_calls == GRAPH_MAX_CRITIC_CALLS
    assert budget.contract_corrections == 0
    assert budget.can_claim_correction is False


def test_contract_correction_ceiling_rejects_without_charging_a_call():
    budget = GraphReviewBudget(
        critic_calls=0,
        contract_corrections=GRAPH_MAX_CONTRACT_CORRECTIONS,
    )

    with pytest.raises(GraphReviewBudgetExceeded, match="contract-correction ceiling"):
        budget.claim_provider_call(correction=True)

    assert budget.critic_calls == 0
    assert budget.contract_corrections == GRAPH_MAX_CONTRACT_CORRECTIONS
    assert budget.can_claim_correction is False

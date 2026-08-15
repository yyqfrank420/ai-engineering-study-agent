import pytest

from agent.graph_review_budget import GraphReviewBudget, GraphReviewBudgetExceeded
from config import (
    GRAPH_MAX_CONTRACT_CORRECTIONS,
    GRAPH_MAX_CRITIC_CALLS,
    GRAPH_MAX_PROTOCOL_CORRECTIONS,
)


def test_correction_claims_are_accounted_separately():
    budget = GraphReviewBudget()

    budget.claim_provider_call(correction=None)
    budget.claim_provider_call(correction="protocol")
    budget.claim_provider_call(correction="contract")

    assert budget.critic_calls == 3
    assert budget.protocol_corrections == 1
    assert budget.contract_corrections == 1
    assert budget.state_counters() == {
        "graph_critic_call_count": 3,
        "graph_protocol_correction_count": 1,
        "graph_contract_correction_count": 1,
    }


def test_provider_call_ceiling_rejects_without_charging_either_counter():
    budget = GraphReviewBudget(
        critic_calls=GRAPH_MAX_CRITIC_CALLS,
        contract_corrections=0,
    )

    with pytest.raises(GraphReviewBudgetExceeded, match="provider-call ceiling"):
        budget.claim_provider_call(correction="contract")

    assert budget.critic_calls == GRAPH_MAX_CRITIC_CALLS
    assert budget.contract_corrections == 0
    assert budget.can_claim_contract_correction is False


def test_contract_correction_ceiling_rejects_without_charging_a_call():
    budget = GraphReviewBudget(
        critic_calls=0,
        contract_corrections=GRAPH_MAX_CONTRACT_CORRECTIONS,
    )

    with pytest.raises(GraphReviewBudgetExceeded, match="contract-correction ceiling"):
        budget.claim_provider_call(correction="contract")

    assert budget.critic_calls == 0
    assert budget.contract_corrections == GRAPH_MAX_CONTRACT_CORRECTIONS
    assert budget.can_claim_contract_correction is False


def test_protocol_correction_ceiling_does_not_consume_contract_correction():
    budget = GraphReviewBudget(
        critic_calls=1,
        protocol_corrections=GRAPH_MAX_PROTOCOL_CORRECTIONS,
    )

    with pytest.raises(GraphReviewBudgetExceeded, match="protocol-correction ceiling"):
        budget.claim_provider_call(correction="protocol")

    assert budget.critic_calls == 1
    assert budget.protocol_corrections == GRAPH_MAX_PROTOCOL_CORRECTIONS
    assert budget.contract_corrections == 0
    assert budget.can_claim_contract_correction is True


@pytest.mark.parametrize("correction", [False, True, "unknown"])
def test_unknown_correction_kind_is_rejected_without_charging(correction):
    budget = GraphReviewBudget()

    with pytest.raises(ValueError, match="unknown graph correction kind"):
        budget.claim_provider_call(correction=correction)  # type: ignore[arg-type]

    assert budget.critic_calls == 0
    assert budget.protocol_corrections == 0
    assert budget.contract_corrections == 0

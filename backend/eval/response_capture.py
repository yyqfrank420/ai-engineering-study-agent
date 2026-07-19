from __future__ import annotations


def _extract_single_response(events: list[dict]) -> str:
    streamed_text = "".join(
        str(event.get("content") or "")
        for event in events
        if event.get("type") == "response_delta"
    )
    explanation_blocks = [
        str(event.get("content") or "")
        for event in events
        if event.get("type") == "explanation_block" and event.get("content")
    ]
    return "\n\n".join(part for part in [streamed_text, *explanation_blocks] if part)


def extract_response_turns(events: list[dict]) -> list[str]:
    """Reconstruct assistant responses without losing conversation boundaries.

    A browser journey may contain several user turns. Treating their responses as
    one answer makes a later instruction appear to include everything said before
    it. A response reset also supersedes the partial draft from the same turn.
    """
    turns: list[str] = []
    current_events: list[dict] = []
    for event in events:
        event_type = event.get("type")
        if event_type == "response_reset":
            current_events = []
            continue
        current_events.append(event)
        if event_type != "done":
            continue
        response = _extract_single_response(current_events)
        if response:
            turns.append(response)
        current_events = []

    response = _extract_single_response(current_events)
    if response:
        turns.append(response)
    return turns


def extract_response_text(events: list[dict]) -> str:
    return "\n\n".join(extract_response_turns(events))

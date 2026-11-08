from app.agent.prompt import SYSTEM_PROMPT


def test_prompt_asks_before_using_a_value_that_is_not_in_the_data() -> None:
    # A typo or a near-miss ("incomplete" vs 'failed') must lead to a question, not a silent 0.
    for rule in (
        "SELECT DISTINCT",
        "Did you mean",
        "do not substitute another value yourself",
    ):
        assert rule in SYSTEM_PROMPT

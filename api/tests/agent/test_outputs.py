from app.agent.outputs import unverified_file_claims


def test_flags_charts_that_were_never_delivered() -> None:
    answer = (
        "Chart: `region_change.png` (exported). Report: report.md. Also monthly.csv was loaded."
    )
    assert unverified_file_claims(answer, {"report.md"}) == ["region_change.png"]


def test_no_claims_when_everything_is_delivered() -> None:
    answer = "See monthly_rev.png and REPORT.MD for details."
    assert unverified_file_claims(answer, {"monthly_rev.png", "report.md"}) == []


def test_data_csv_mentions_are_not_flagged() -> None:
    assert unverified_file_claims("I loaded data.csv and summary.csv.", set()) == []


def test_claims_are_deduplicated_and_sorted() -> None:
    answer = "b.png a.png b.png"
    assert unverified_file_claims(answer, set()) == ["a.png", "b.png"]

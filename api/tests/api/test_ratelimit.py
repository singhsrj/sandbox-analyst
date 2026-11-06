from app.ratelimit import RateLimiter


def test_allows_up_to_the_limit_then_blocks() -> None:
    limiter = RateLimiter(3, window_seconds=60)
    assert [limiter.allow("a", now=t) for t in (0, 1, 2)] == [True, True, True]
    assert limiter.allow("a", now=3) is False


def test_window_slides() -> None:
    limiter = RateLimiter(2, window_seconds=10)
    assert limiter.allow("a", now=0) and limiter.allow("a", now=1)
    assert not limiter.allow("a", now=5)
    assert limiter.allow("a", now=10)  # the first hit has aged out


def test_keys_are_independent() -> None:
    limiter = RateLimiter(1, window_seconds=60)
    assert limiter.allow("a", now=0) and limiter.allow("b", now=0)
    assert not limiter.allow("a", now=1)


def test_retry_after_is_positive_while_blocked() -> None:
    limiter = RateLimiter(1, window_seconds=60)
    limiter.allow("a", now=0)
    assert not limiter.allow("a", now=10)
    assert 49 <= limiter.retry_after("a", now=10) <= 52
    assert limiter.retry_after("unknown") == 0


def test_memory_is_bounded_when_keys_are_sprayed() -> None:
    limiter = RateLimiter(1, window_seconds=1)
    for i in range(10_050):
        limiter.allow(f"k{i}", now=0)
    limiter.allow("fresh", now=100)
    assert len(limiter._hits) < 10_050

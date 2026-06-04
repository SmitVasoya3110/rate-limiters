import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Callable, Optional
from fastapi import Request

logger = logging.getLogger(__name__)


@dataclass
class RateLimitRule:
    """Policy for a single bucket: how many requests, over what window, keyed how."""
    limit: int
    period: int
    key_func: Optional[Callable[[Request], str]] = None


@dataclass
class RateLimitDecision:
    """Fully-resolved instruction handed to the middleware. The middleware only
    needs these three values; it has no idea how they were derived."""
    limit: int
    period: int
    identifier: str


class Outcome:
    """What a resolver decided about a request. Three terminal meanings, so
    illegal states (e.g. "skip" *and* a decision at once) can't be represented:

    - :class:`Limit`  -> apply a concrete decision
    - :data:`SKIP`    -> bypass rate limiting entirely
    - :data:`DEFER`   -> no opinion; ask the next resolver in the chain

    The middleware only reads ``.decision`` (``None`` for SKIP/DEFER), so it
    stays ignorant of the taxonomy."""
    decision: Optional[RateLimitDecision] = None


@dataclass(frozen=True)
class Limit(Outcome):
    """Apply this concrete, fully-resolved decision."""
    decision: RateLimitDecision


class _Skip(Outcome):
    """Bypass rate limiting for this request (terminal)."""


class _Defer(Outcome):
    """This resolver has no opinion; ask the next link in the chain."""


SKIP = _Skip()
DEFER = _Defer()


class RuleResolver(ABC):
    """Separates *policy* (which limits apply to a request) from *mechanism*
    (the middleware that enforces a limit).

    Implementations can be static, read from Redis/a database, vary by
    subscription tier, etc., and can be composed via :class:`ChainResolver`
    (Chain of Responsibility). Return :class:`Limit` to apply a decision,
    :data:`SKIP` to bypass, or :data:`DEFER` to let the next resolver decide."""

    @abstractmethod
    async def resolve(self, request: Request) -> Outcome:
        ...


def default_ip_key(request: Request) -> str:
    client_ip = request.client.host if request.client else "unknown"
    return f"ip:{client_ip}"


def as_limit(
    rule: RateLimitRule,
    request: Request,
    default_key_func: Callable[[Request], str] = default_ip_key,
) -> Limit:
    """Centralized identifier resolution: turn a policy :class:`RateLimitRule`
    into a :class:`Limit` outcome. This is the *single* place that applies a
    key function, so chain links never duplicate identifier logic."""
    key_func = rule.key_func or default_key_func
    decision = RateLimitDecision(limit=rule.limit, period=rule.period, identifier=key_func(request))
    return Limit(decision)


class StaticRuleResolver(RuleResolver):
    """In-memory resolver configured at startup. Reproduces the original
    path-rules behaviour while keeping the middleware decoupled."""

    def __init__(
        self,
        default_limit: int,
        default_period: int,
        default_key_func: Callable[[Request], str] = default_ip_key,
        path_rules: Optional[dict[str, RateLimitRule]] = None,
        excluded_paths: Optional[list[str]] = None,
    ):
        logger.info(
            f"[rules/StaticRuleResolver.__init__] invoked | default_limit={default_limit} "
            f"default_period={default_period} excluded={excluded_paths} "
            f"paths={list((path_rules or {}).keys())}"
        )
        self.default_limit = default_limit
        self.default_period = default_period
        self.default_key_func = default_key_func
        self.path_rules = path_rules or {}
        self.excluded_paths = set(excluded_paths or [])

    async def resolve(self, request: Request) -> Outcome:
        path = request.url.path
        logger.info(f"[rules/StaticRuleResolver.resolve] invoked | path={path}")
        if path in self.excluded_paths:
            logger.info(f"[rules/StaticRuleResolver.resolve] excluded, bypassing | path={path}")
            return SKIP

        rule = self.path_rules.get(path)
        if rule is None:
            rule = RateLimitRule(limit=self.default_limit, period=self.default_period)
        return as_limit(rule, request, self.default_key_func)


class ChainResolver(RuleResolver):
    """Chain of Responsibility: ask each link in order; the first link that
    returns a non-:data:`DEFER` outcome wins. Put the most specific/dynamic
    links first and a terminal resolver (e.g. :class:`StaticRuleResolver`,
    which never defers) last.

    Composable: a :class:`ChainResolver` is itself a :class:`RuleResolver`, so
    chains can be nested."""

    def __init__(self, links: list[RuleResolver]):
        logger.info(f"[rules/ChainResolver.__init__] invoked | links={[type(l).__name__ for l in links]}")
        self.links = list(links)

    async def resolve(self, request: Request) -> Outcome:
        logger.info(f"[rules/ChainResolver.resolve] invoked | path={request.url.path}")
        for link in self.links:
            outcome = await link.resolve(request)
            if outcome is not DEFER:
                logger.info(f"[rules/ChainResolver.resolve] handled by {type(link).__name__}")
                return outcome
        logger.info("[rules/ChainResolver.resolve] no link handled, deferring")
        return DEFER


class RedisOverrideResolver(RuleResolver):
    """Example chain link: evolve limits without code changes by reading a
    per-subscription override from the shared Redis client. Returns:

    - :data:`SKIP`  for an explicit bypass (e.g. enterprise customers),
    - a :class:`Limit` for a tier-specific limit,
    - :data:`DEFER` when there's no override, so the next resolver decides.

    Expected Redis layout (one hash per tier)::

        HSET ratelimit:tier:enterprise bypass 1
        HSET ratelimit:tier:pro        limit 5000 period 60

    The tier is read from ``request.state.<tier_attr>`` (default
    ``subscription``), which an upstream auth middleware would populate."""

    def __init__(
        self,
        default_key_func: Callable[[Request], str] = default_ip_key,
        key_prefix: str = "ratelimit:tier:",
        tier_attr: str = "subscription",
    ):
        logger.info("[rules/RedisOverrideResolver.__init__] invoked")
        self.default_key_func = default_key_func
        self.key_prefix = key_prefix
        self.tier_attr = tier_attr

    async def resolve(self, request: Request) -> Outcome:
        tier = getattr(request.state, self.tier_attr, None)
        logger.info(f"[rules/RedisOverrideResolver.resolve] invoked | tier={tier}")
        if not tier:
            return DEFER

        logger.info("[rules/RedisOverrideResolver.resolve] -> redis.hgetall")
        raw = await request.app.state.redis.hgetall(f"{self.key_prefix}{tier}")
        if not raw:
            return DEFER

        if str(raw.get("bypass", "")).lower() in ("1", "true", "yes"):
            logger.info("[rules/RedisOverrideResolver.resolve] bypass override -> SKIP")
            return SKIP

        rule = RateLimitRule(limit=int(raw["limit"]), period=int(raw["period"]))
        logger.info(f"[rules/RedisOverrideResolver.resolve] tier override -> limit={rule.limit} period={rule.period}")
        return as_limit(rule, request, self.default_key_func)

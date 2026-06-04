import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Awaitable, Callable, Optional
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


class RuleResolver(ABC):
    """Separates *policy* (which limits apply to a request) from *mechanism*
    (the middleware that enforces a limit).

    Implementations can be static, read from Redis/a database, vary by
    subscription tier, etc. Returning ``None`` means "do not rate-limit this
    request" (e.g. excluded paths)."""

    @abstractmethod
    async def resolve(self, request: Request) -> Optional[RateLimitDecision]:
        ...


def default_ip_key(request: Request) -> str:
    client_ip = request.client.host if request.client else "unknown"
    return f"ip:{client_ip}"


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

    async def resolve(self, request: Request) -> Optional[RateLimitDecision]:
        path = request.url.path
        logger.info(f"[rules/StaticRuleResolver.resolve] invoked | path={path}")
        if path in self.excluded_paths:
            logger.info(f"[rules/StaticRuleResolver.resolve] excluded, no limit | path={path}")
            return None

        rule = self.path_rules.get(path)
        if rule is not None:
            limit, period = rule.limit, rule.period
            key_func = rule.key_func or self.default_key_func
        else:
            limit, period = self.default_limit, self.default_period
            key_func = self.default_key_func

        return RateLimitDecision(limit=limit, period=period, identifier=key_func(request))


# Source that may yield a dynamic override for a request (e.g. from Redis/DB),
# or None to defer to the fallback resolver.
OverrideSource = Callable[[Request], Awaitable[Optional[RateLimitRule]]]


class DynamicRuleResolver(RuleResolver):
    """Evolve limits without code changes: an async ``override_source`` is
    consulted first (read it from Redis, a database, a feature flag, the user's
    subscription tier, etc.). If it yields a rule, that wins; otherwise we fall
    back to ``base`` (typically a :class:`StaticRuleResolver`).

    Example override_source reading a per-tier limit from the shared Redis
    client::

        async def from_redis(request):
            tier = getattr(request.state, "subscription", None)
            if not tier:
                return None
            raw = await request.app.state.redis.hgetall(f"ratelimit:tier:{tier}")
            if not raw:
                return None
            return RateLimitRule(limit=int(raw["limit"]), period=int(raw["period"]))

        resolver = DynamicRuleResolver(base=static_resolver, override_source=from_redis)
    """

    def __init__(self, base: RuleResolver, override_source: OverrideSource):
        logger.info("[rules/DynamicRuleResolver.__init__] invoked")
        self.base = base
        self.override_source = override_source

    async def resolve(self, request: Request) -> Optional[RateLimitDecision]:
        logger.info(f"[rules/DynamicRuleResolver.resolve] invoked | path={request.url.path}")
        logger.info("[rules/DynamicRuleResolver.resolve] -> override_source")
        rule = await self.override_source(request)
        if rule is not None:
            logger.info("[rules/DynamicRuleResolver.resolve] override applied")
            key_func = rule.key_func or default_ip_key
            return RateLimitDecision(limit=rule.limit, period=rule.period, identifier=key_func(request))

        logger.info("[rules/DynamicRuleResolver.resolve] -> base.resolve (fallback)")
        return await self.base.resolve(request)

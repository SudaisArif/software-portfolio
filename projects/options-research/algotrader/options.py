import math
from dataclasses import dataclass
from statistics import NormalDist


@dataclass(frozen=True)
class OptionGreeks:
    price: float
    delta: float
    gamma: float
    theta: float
    vega: float
    rho: float


def normal_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def normal_pdf(x: float) -> float:
    return math.exp(-0.5 * x * x) / math.sqrt(2.0 * math.pi)


def normal_inv_cdf(p: float) -> float:
    if not 0.0 < p < 1.0:
        raise ValueError("p must be between 0 and 1")
    return NormalDist().inv_cdf(p)


def _d1_d2(s: float, k: float, t: float, r: float, sigma: float, q: float) -> tuple:
    if s <= 0.0 or k <= 0.0 or t <= 0.0 or sigma <= 0.0:
        raise ValueError("s, k, t, and sigma must be positive")
    d1 = (math.log(s / k) + (r - q + 0.5 * sigma * sigma) * t) / (sigma * math.sqrt(t))
    d2 = d1 - sigma * math.sqrt(t)
    return d1, d2


def black_scholes_price(
    s: float,
    k: float,
    t: float,
    r: float,
    sigma: float,
    option_type: str = "call",
    q: float = 0.0,
) -> float:
    d1, d2 = _d1_d2(s, k, t, r, sigma, q)
    disc_q = math.exp(-q * t)
    disc_r = math.exp(-r * t)
    if option_type.lower() == "call":
        return s * disc_q * normal_cdf(d1) - k * disc_r * normal_cdf(d2)
    if option_type.lower() == "put":
        return k * disc_r * normal_cdf(-d2) - s * disc_q * normal_cdf(-d1)
    raise ValueError("option_type must be 'call' or 'put'")


def black_scholes_greeks(
    s: float,
    k: float,
    t: float,
    r: float,
    sigma: float,
    option_type: str = "call",
    q: float = 0.0,
) -> OptionGreeks:
    d1, d2 = _d1_d2(s, k, t, r, sigma, q)
    disc_q = math.exp(-q * t)
    disc_r = math.exp(-r * t)
    price = black_scholes_price(s, k, t, r, sigma, option_type, q)
    gamma = disc_q * normal_pdf(d1) / (s * sigma * math.sqrt(t))
    vega = s * disc_q * normal_pdf(d1) * math.sqrt(t) / 100.0
    if option_type.lower() == "call":
        delta = disc_q * normal_cdf(d1)
        theta = (
            -s * disc_q * normal_pdf(d1) * sigma / (2.0 * math.sqrt(t))
            - r * k * disc_r * normal_cdf(d2)
            + q * s * disc_q * normal_cdf(d1)
        ) / 365.0
        rho = k * t * disc_r * normal_cdf(d2) / 100.0
    elif option_type.lower() == "put":
        delta = -disc_q * normal_cdf(-d1)
        theta = (
            -s * disc_q * normal_pdf(d1) * sigma / (2.0 * math.sqrt(t))
            + r * k * disc_r * normal_cdf(-d2)
            - q * s * disc_q * normal_cdf(-d1)
        ) / 365.0
        rho = -k * t * disc_r * normal_cdf(-d2) / 100.0
    else:
        raise ValueError("option_type must be 'call' or 'put'")
    return OptionGreeks(price=price, delta=delta, gamma=gamma, theta=theta, vega=vega, rho=rho)


def implied_volatility(
    market_price: float,
    s: float,
    k: float,
    t: float,
    r: float,
    option_type: str = "call",
    q: float = 0.0,
    low: float = 0.01,
    high: float = 3.0,
    tolerance: float = 1e-6,
    max_iter: int = 100,
) -> float:
    lo = low
    hi = high
    for _ in range(max_iter):
        mid = (lo + hi) / 2.0
        price = black_scholes_price(s, k, t, r, mid, option_type, q)
        if abs(price - market_price) <= tolerance:
            return mid
        if price < market_price:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2.0


def inverse_gaussian_cdf(x: float, mu: float, lam: float = 1.0) -> float:
    if x <= 0.0:
        return 0.0
    if mu <= 0.0 or lam <= 0.0:
        raise ValueError("mu and lam must be positive")
    root = math.sqrt(lam / x)
    first = normal_cdf(root * (x / mu - 1.0))
    second = math.exp(2.0 * lam / mu) * normal_cdf(-root * (x / mu + 1.0))
    return min(1.0, max(0.0, first + second))


def inverse_gaussian_ppf(p: float, mu: float, lam: float = 1.0, tolerance: float = 1e-12, max_iter: int = 120) -> float:
    if not 0.0 < p < 1.0:
        raise ValueError("p must be between 0 and 1")
    if mu <= 0.0 or lam <= 0.0:
        raise ValueError("mu and lam must be positive")
    lo = 0.0
    hi = max(mu, 1e-12)
    while inverse_gaussian_cdf(hi, mu, lam) < p:
        hi *= 2.0
        if hi > 1e12:
            break
    for _ in range(max_iter):
        mid = (lo + hi) / 2.0
        value = inverse_gaussian_cdf(mid, mu, lam)
        if abs(value - p) <= tolerance:
            return mid
        if value < p:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2.0


def implied_volatility_inverse_gaussian(
    market_price: float,
    s: float,
    k: float,
    t: float,
    r: float,
    option_type: str = "call",
    q: float = 0.0,
) -> float:
    """Implied volatility via the inverse-Gaussian transform in arXiv:2604.24480.

    This uses the paper's Black-Scholes inversion identity. Without SciPy we compute
    the inverse-Gaussian quantile by bisection, so this is mainly a correctness utility
    for now rather than a speed replacement for the existing bisection IV solver.
    """
    if market_price <= 0.0 or s <= 0.0 or k <= 0.0 or t <= 0.0:
        raise ValueError("market_price, s, k, and t must be positive")
    disc_q = math.exp(-q * t)
    disc_r = math.exp(-r * t)
    forward = s * math.exp((r - q) * t)
    option = option_type.lower()
    if option == "put":
        call_price = market_price + s * disc_q - k * disc_r
    elif option == "call":
        call_price = market_price
    else:
        raise ValueError("option_type must be 'call' or 'put'")

    normalized_call = call_price / (disc_r * forward)
    log_moneyness = math.log(k / forward)
    intrinsic = max(1.0 - k / forward, 0.0)
    if not intrinsic < normalized_call < 1.0:
        raise ValueError("market_price is outside the strict Black-Scholes no-arbitrage range")
    if abs(log_moneyness) <= 1e-12:
        return 2.0 * normal_inv_cdf((normalized_call + 1.0) / 2.0) / math.sqrt(t)

    m = 1.0 if log_moneyness > 0.0 else k / forward
    probability = (1.0 - normalized_call) / m
    quantile = inverse_gaussian_ppf(probability, 2.0 / abs(log_moneyness), 1.0)
    return 2.0 / (math.sqrt(t) * math.sqrt(quantile))

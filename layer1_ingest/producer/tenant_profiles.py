import random

random.seed(42)  # reproducible profiles across runs

PLAN_DISTRIBUTION = [
    ("free",       0.40),
    ("starter",    0.30),
    ("growth",     0.20),
    ("enterprise", 0.10),
]

def _pick_plan() -> str:
    r = random.random()
    cumulative = 0.0
    for plan, prob in PLAN_DISTRIBUTION:
        cumulative += prob
        if r < cumulative:
            return plan
    return "growth"

def _events_per_second(plan: str) -> tuple[float, float]:
    return {
        "free":       (0.05, 0.3),
        "starter":    (0.3,  1.0),
        "growth":     (1.0,  4.0),
        "enterprise": (4.0, 15.0),
    }[plan]

def _build_tenant(i: int) -> dict:
    plan = _pick_plan()
    return {
        "tenant_id":    f"tenant_{i:03d}",
        "plan":         plan,
        "user_count":   {"free": 5, "starter": 20,
                         "growth": 100, "enterprise": 500}[plan],
        "eps_range":    _events_per_second(plan),
        "silence_prob": {"free": 0.20, "starter": 0.10,
                         "growth": 0.04, "enterprise": 0.01}[plan],
        "feature_weights": {
            "dashboard":       random.uniform(0.1, 1.0),
            "reports":         random.uniform(0.1, 1.0),
            "exports":         random.uniform(0.0, 0.5),
            "integrations":    random.uniform(0.0, 0.8),
            "ai_assistant":    random.uniform(0.0, 0.9),
            "user_management": random.uniform(0.05, 0.3),
            "billing":         random.uniform(0.02, 0.1),
            "api_keys":        random.uniform(0.0, 0.4),
        },
    }

TENANTS: dict[str, dict] = {
    f"tenant_{i:03d}": _build_tenant(i)
    for i in range(1, 51)
}

def is_tenant_silent(tenant_id: str) -> bool:
    return random.random() < TENANTS[tenant_id]["silence_prob"]

def get_inter_event_delay(tenant_id: str) -> float:
    lo, hi = TENANTS[tenant_id]["eps_range"]
    return 1.0 / random.uniform(lo, hi)

def pick_user(tenant_id: str) -> str:
    return f"user_{random.randint(1, TENANTS[tenant_id]['user_count']):04d}"

def pick_feature(tenant_id: str) -> str:
    weights = TENANTS[tenant_id]["feature_weights"]
    return random.choices(list(weights.keys()), weights=list(weights.values()), k=1)[0]

"""Six demo incidents for the diagnostics engine.

Each has a different crash location, different error type, and a different
root cause — so the engine has to trace a different path each time.

  Trace 1  charge() crashes              root cause: get_payment_timeout
  Trace 2  create_session() crashes      root cause: load_timeout
  Trace 3  place_order() crashes         root cause: get_cart
  Trace A  validate_token() crashes      root cause: connect  (database.py)
  Trace B  place_order_fresh() crashes   root cause: flush    (cache.py)
  Trace C  build_payload() crashes       root cause: build_payload (notification.py)

SEEDING:
  Each trace needs a different node seeded with a recent git commit so the
  engine's git_confirms check fires on the correct root cause.
  See SEED_* dicts below — pass the matching one to seed_graph().
"""
import os
import pickle

_D = os.path.join(os.path.dirname(os.path.abspath(__file__)), "demo-codebase")
_GRAPH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output", "demo-codebase_graph.pkl")

# ── Trace 1 ───────────────────────────────────────────────────────────────────
# charge() tries to access cart.total but cart is None.
# cart comes from get_cart() which returns None when payment timeout is 0.
# Root cause: get_payment_timeout() was changed to return 0.
TRACE_CART_NONE = f"""\
Traceback (most recent call last):
  File "{_D}/app.py", line 7, in handle_request
    return service.place_order(request.cart)
  File "{_D}/order.py", line 7, in place_order
    payment.charge(cart.total)
  File "{_D}/payment.py", line 9, in charge
    return cart.total
AttributeError: 'NoneType' object has no attribute 'total'
"""

SEED_1 = {
    "get_payment_timeout": ("2026-06-13T10:00:00Z", "reduce payment timeout for perf"),
}

# ── Trace 2 ───────────────────────────────────────────────────────────────────
# create_session() fails because load_timeout() was recently changed to
# return a float instead of int, breaking the == 0 check downstream.
# Root cause: load_timeout() — the return type change broke session init.
TRACE_SESSION_INIT = f"""\
Traceback (most recent call last):
  File "{_D}/app.py", line 7, in handle_request
    return service.place_order(request.cart)
  File "{_D}/order.py", line 7, in place_order
    payment.charge(cart.total)
  File "{_D}/payment.py", line 7, in charge
    session.create_session()
  File "{_D}/session.py", line 6, in create_session
    self.active = True
ValueError: payment session could not be initialised — timeout config is invalid
"""

SEED_2 = {
    "load_timeout": ("2026-06-12T14:00:00Z", "refactor load_timeout to support float precision"),
}

# ── Trace 3 ───────────────────────────────────────────────────────────────────
# place_order() fails early — only 2 frames visible in the trace.
# The engine cannot see the cause from the traceback alone and must
# traverse 3 hops to find get_cart(), which was recently modified to
# always return None as part of a session refactor.
# Root cause: get_cart() — change silently broke cart retrieval.
TRACE_ORDER_FAILED = f"""\
Traceback (most recent call last):
  File "{_D}/app.py", line 7, in handle_request
    return service.place_order(request.cart)
  File "{_D}/order.py", line 7, in place_order
    payment.charge(cart.total)
RuntimeError: payment processing failed — cart is unavailable
"""

SEED_3 = {
    "get_cart": ("2026-06-11T09:00:00Z", "rewrite get_cart session lookup logic"),
}


# ── Trace A ───────────────────────────────────────────────────────────────────
# handle_auth_request() calls validate_token() which calls query() which calls
# connect() — connect() raises ConnectionError because DATABASE_TIMEOUT is 0.
# Root cause: connect() in database.py was recently changed to enforce the timeout.
TRACE_DB_CONNECT = f"""\
Traceback (most recent call last):
  File "{_D}/app.py", line 13, in handle_auth_request
    AuthService().validate_token(request.token)
  File "{_D}/auth.py", line 7, in validate_token
    return DatabaseConnection().query("SELECT 1 FROM tokens WHERE val=?", token)
  File "{_D}/database.py", line 13, in query
    self.connect()
  File "{_D}/database.py", line 7, in connect
    raise ConnectionError("database connect timeout — DATABASE_TIMEOUT is 0")
ConnectionError: database connect timeout — DATABASE_TIMEOUT is 0
"""

SEED_A = {
    "connect": ("2026-06-14T09:00:00Z", "enforce DATABASE_TIMEOUT in connect — zero means no connection"),
}

# ── Trace B ───────────────────────────────────────────────────────────────────
# place_order_fresh() calls flush() which raises RuntimeError because
# MAX_RETRIES is 0 — cache invalidation is disabled.
# Root cause: flush() in cache.py — recently changed to respect MAX_RETRIES.
TRACE_CACHE_FLUSH = f"""\
Traceback (most recent call last):
  File "{_D}/app.py", line 9, in handle_request
    return service.place_order(request.cart)
  File "{_D}/order.py", line 13, in place_order_fresh
    CacheManager().flush(cart.id)
  File "{_D}/cache.py", line 16, in flush
    raise RuntimeError("cache flush failed — MAX_RETRIES is 0")
RuntimeError: cache flush failed — MAX_RETRIES is 0
"""

SEED_B = {
    "flush": ("2026-06-15T11:00:00Z", "add MAX_RETRIES guard to cache flush"),
}

# ── Trace C ───────────────────────────────────────────────────────────────────
# send_payment_notification() → send() → build_payload() — build_payload calls
# get_payment_timeout() which returns 0, setting label=None, then label.upper() crashes.
# Root cause: build_payload() — recently changed to include timeout in the payload.
TRACE_NOTIFICATION = f"""\
Traceback (most recent call last):
  File "{_D}/app.py", line 18, in send_payment_notification
    return NotificationService().send(amount)
  File "{_D}/notification.py", line 7, in send
    payload = self.build_payload(amount)
  File "{_D}/notification.py", line 14, in build_payload
    return {{"amount": amount, "label": label.upper()}}
AttributeError: 'NoneType' object has no attribute 'upper'
"""

SEED_C = {
    "build_payload": ("2026-06-16T08:00:00Z", "add payment timeout label to notification payload"),
}


# ── graph seeding helper ──────────────────────────────────────────────────────

def seed_graph(seed: dict) -> object:
    """Load the graph and stamp the seed nodes with recent commit dates."""
    graph = pickle.load(open(_GRAPH, "rb"))
    for n in graph.all_nodes():
        meta = n.metadata if isinstance(n.metadata, dict) else {}
        if n.name in seed:
            date, msg = seed[n.name]
            meta["last_commit_date"]    = date
            meta["last_commit_message"] = msg
        else:
            meta["last_commit_date"]    = "2025-02-01T10:00:00Z"
            meta["last_commit_message"] = "initial implementation"
        n.metadata = meta
    pickle.dump(graph, open(_GRAPH, "wb"))
    return graph

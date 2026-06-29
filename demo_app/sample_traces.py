"""Sample stacktraces and their git seeds for the demo web app."""
import os

_D = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "demo-codebase")

PRESETS = {
    "trace_1": {
        "label": "AttributeError in charge() — cart is None (3 hops to root cause)",
        "seed_node": "get_payment_timeout",
        "seed_date": "2026-06-13T10:00:00Z",
        "seed_msg":  "reduce payment timeout for perf",
        "trace": (
            f'Traceback (most recent call last):\n'
            f'  File "{_D}/app.py", line 9, in handle_request\n'
            f'    return service.place_order(request.cart)\n'
            f'  File "{_D}/order.py", line 8, in place_order\n'
            f'    payment.charge(cart.total)\n'
            f'  File "{_D}/payment.py", line 9, in charge\n'
            f'    return cart.total\n'
            f"AttributeError: 'NoneType' object has no attribute 'total'\n"
        ),
    },
    "trace_2": {
        "label": "ValueError in create_session() — timeout config invalid (2 hops)",
        "seed_node": "load_timeout",
        "seed_date": "2026-06-12T14:00:00Z",
        "seed_msg":  "refactor load_timeout to support float precision",
        "trace": (
            f'Traceback (most recent call last):\n'
            f'  File "{_D}/app.py", line 9, in handle_request\n'
            f'    return service.place_order(request.cart)\n'
            f'  File "{_D}/order.py", line 8, in place_order\n'
            f'    payment.charge(cart.total)\n'
            f'  File "{_D}/payment.py", line 7, in charge\n'
            f'    session.create_session()\n'
            f'  File "{_D}/session.py", line 6, in create_session\n'
            f'    self.active = True\n'
            f'ValueError: payment session could not be initialised — timeout config is invalid\n'
        ),
    },
    "trace_3": {
        "label": "RuntimeError in place_order() — cart unavailable (2 hops, short trace)",
        "seed_node": "get_cart",
        "seed_date": "2026-06-11T09:00:00Z",
        "seed_msg":  "rewrite get_cart session lookup logic",
        "trace": (
            f'Traceback (most recent call last):\n'
            f'  File "{_D}/app.py", line 9, in handle_request\n'
            f'    return service.place_order(request.cart)\n'
            f'  File "{_D}/order.py", line 8, in place_order\n'
            f'    payment.charge(cart.total)\n'
            f'RuntimeError: payment processing failed — cart is unavailable\n'
        ),
    },
    "trace_a": {
        "label": "ConnectionError in validate_token() — DATABASE_TIMEOUT is 0",
        "seed_node": "connect",
        "seed_date": "2026-06-14T09:00:00Z",
        "seed_msg":  "enforce DATABASE_TIMEOUT in connect — zero means no connection",
        "trace": (
            f'Traceback (most recent call last):\n'
            f'  File "{_D}/app.py", line 13, in handle_auth_request\n'
            f'    AuthService().validate_token(request.token)\n'
            f'  File "{_D}/auth.py", line 7, in validate_token\n'
            f'    return DatabaseConnection().query("SELECT 1 FROM tokens WHERE val=?", token)\n'
            f'  File "{_D}/database.py", line 13, in query\n'
            f'    self.connect()\n'
            f'  File "{_D}/database.py", line 7, in connect\n'
            f'    raise ConnectionError("database connect timeout — DATABASE_TIMEOUT is 0")\n'
            f'ConnectionError: database connect timeout — DATABASE_TIMEOUT is 0\n'
        ),
    },
    "trace_b": {
        "label": "RuntimeError in place_order_fresh() — MAX_RETRIES is 0",
        "seed_node": "flush",
        "seed_date": "2026-06-15T11:00:00Z",
        "seed_msg":  "add MAX_RETRIES guard to cache flush",
        "trace": (
            f'Traceback (most recent call last):\n'
            f'  File "{_D}/app.py", line 9, in handle_request\n'
            f'    return service.place_order(request.cart)\n'
            f'  File "{_D}/order.py", line 13, in place_order_fresh\n'
            f'    CacheManager().flush(cart.id)\n'
            f'  File "{_D}/cache.py", line 16, in flush\n'
            f'    raise RuntimeError("cache flush failed — MAX_RETRIES is 0")\n'
            f'RuntimeError: cache flush failed — MAX_RETRIES is 0\n'
        ),
    },
    "trace_c": {
        "label": "AttributeError in build_payload() — notification label is None",
        "seed_node": "build_payload",
        "seed_date": "2026-06-16T08:00:00Z",
        "seed_msg":  "add payment timeout label to notification payload",
        "trace": (
            f'Traceback (most recent call last):\n'
            f'  File "{_D}/app.py", line 18, in send_payment_notification\n'
            f'    return NotificationService().send(amount)\n'
            f'  File "{_D}/notification.py", line 7, in send\n'
            f'    payload = self.build_payload(amount)\n'
            f'  File "{_D}/notification.py", line 14, in build_payload\n'
            f'    return {{"amount": amount, "label": label.upper()}}\n'
            f"AttributeError: 'NoneType' object has no attribute 'upper'\n"
        ),
    },
}

PRIMARY_TRACE = PRESETS["trace_1"]["trace"]

# Files visible in the primary trace — used by compare_haiku.py to show
# what a naked LLM has access to vs what the graph engine surfaces.
TRACEBACK_FILES = ["app.py", "order.py", "payment.py"]

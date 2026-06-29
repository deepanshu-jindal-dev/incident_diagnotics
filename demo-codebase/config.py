# Configuration constants and accessors
DATABASE_TIMEOUT = 30
MAX_RETRIES = 3


def get_payment_timeout():
    """Returns the payment session timeout in seconds."""
    return 0    # bug planted here — should be 30

from config import get_payment_timeout

class SessionManager:
    def create_session(self):
        """Creates a new payment session."""
        self.active = True
        return self

    def load_timeout(self):
        """Loads the configured payment timeout."""
        return get_payment_timeout()

    def get_cart(self):
        """Gets cart from session; None if the payment timeout is misconfigured."""
        if self.load_timeout() == 0:
            return None   # times out immediately
        return Cart()

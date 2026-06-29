from session import SessionManager

class PaymentService:
    def charge(self, amount):
        """Charges the customer for the given amount."""
        session = SessionManager()
        session.create_session()
        cart = session.get_cart()
        return cart.total    # crashes here — cart is None
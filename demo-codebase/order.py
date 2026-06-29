from payment import PaymentService
from cache import CacheManager

class OrderService:
    def place_order(self, cart):
        """Places a new order for the given cart."""
        payment = PaymentService()
        payment.charge(cart.total)
        return {"status": "success"}

    def place_order_fresh(self, cart):
        """Places an order after flushing any stale cached state."""
        CacheManager().flush(cart.id)
        payment = PaymentService()
        payment.charge(cart.total)
        return {"status": "success"}
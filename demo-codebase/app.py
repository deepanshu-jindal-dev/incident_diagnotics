from order import OrderService
from auth import AuthService
from notification import NotificationService

class App:
    def handle_request(self, request):
        """Handles incoming order request."""
        service = OrderService()
        return service.place_order(request.cart)

    def handle_auth_request(self, request):
        """Handles an authenticated order request, validating token first."""
        AuthService().validate_token(request.token)
        return OrderService().place_order(request.cart)

    def send_payment_notification(self, amount):
        """Sends a post-payment notification to the customer."""
        return NotificationService().send(amount)
from config import get_payment_timeout


class NotificationService:
    def send(self, amount):
        """Sends a post-payment notification to the customer."""
        payload = self.build_payload(amount)
        return {"status": "sent", "payload": payload}

    def build_payload(self, amount):
        """Builds the notification payload including payment metadata."""
        timeout = get_payment_timeout()
        label = None if timeout == 0 else f"timeout:{timeout}s"
        return {"amount": amount, "label": label.upper()}

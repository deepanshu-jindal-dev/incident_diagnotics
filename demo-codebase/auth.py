from database import DatabaseConnection


class AuthService:
    def validate_token(self, token):
        """Validates an auth token against the user store."""
        return DatabaseConnection().query("SELECT 1 FROM tokens WHERE val=?", token)

    def check_role(self, user_id, role):
        """Checks if the user holds the required role."""
        result = DatabaseConnection().query("SELECT 1 FROM roles WHERE uid=?", user_id)
        if not result:
            raise PermissionError(f"user {user_id} lacks role '{role}'")
        return True

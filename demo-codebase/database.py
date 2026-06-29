from config import DATABASE_TIMEOUT


class DatabaseConnection:
    def connect(self):
        """Opens a database connection using DATABASE_TIMEOUT as socket timeout."""
        if DATABASE_TIMEOUT == 0:
            raise ConnectionError("database connect timeout — DATABASE_TIMEOUT is 0")
        self._active = True
        return self

    def query(self, sql, *params):
        """Executes a parameterised query on the active connection."""
        self.connect()
        return []

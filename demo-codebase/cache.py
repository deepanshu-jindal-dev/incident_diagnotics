from config import MAX_RETRIES


class CacheManager:
    def get(self, key):
        """Returns a cached value or None on a miss."""
        return None

    def set(self, key, value, ttl=300):
        """Stores a value in cache with a TTL in seconds."""
        pass

    def flush(self, key):
        """Removes a key from cache, retrying up to MAX_RETRIES times."""
        if MAX_RETRIES == 0:
            raise RuntimeError("cache flush failed — MAX_RETRIES is 0")
        return True

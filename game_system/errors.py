from network.errors import NetworkError


class AuthError(NetworkError):
    pass


class BlacklistError(NetworkError):
    pass


class FlagLockingError(NetworkError):
    pass
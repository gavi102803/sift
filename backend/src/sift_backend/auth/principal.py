from dataclasses import dataclass


@dataclass(frozen=True)
class CurrentPrincipal:
    user_id: str
    auth_method: str
    is_development_fallback: bool = False
    installation_id: str | None = None


class DevelopmentPrincipalProvider:
    def __init__(self, user_id: str = "local-dev") -> None:
        self.user_id = user_id

    def current_principal(self) -> CurrentPrincipal:
        return CurrentPrincipal(
            user_id=self.user_id,
            auth_method="development",
            is_development_fallback=True,
        )

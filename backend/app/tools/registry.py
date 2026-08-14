from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from pydantic import BaseModel, ValidationError
from sqlalchemy.orm import Session

ToolHandler = Callable[[Session, BaseModel], dict[str, object]]


class ToolNotFoundError(LookupError):
    pass


class ToolAuthorizationError(PermissionError):
    pass


class ToolInputError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ToolDefinition:
    name: str
    description: str
    input_model: type[BaseModel]
    handler: ToolHandler
    allowed_roles: tuple[str, ...] = ("admin",)
    mutating: bool = False

    def json_schema(self) -> dict[str, object]:
        schema = self.input_model.model_json_schema()
        schema.pop("title", None)
        return schema


class ToolRegistry:
    def __init__(self, definitions: list[ToolDefinition]):
        self._definitions = {definition.name: definition for definition in definitions}

    def list(self, actor_role: str) -> list[ToolDefinition]:
        return [
            definition
            for definition in self._definitions.values()
            if actor_role in definition.allowed_roles
        ]

    def call(
        self,
        db: Session,
        name: str,
        arguments: dict[str, object],
        *,
        actor_role: str,
    ) -> dict[str, object]:
        definition = self._definitions.get(name)
        if definition is None:
            raise ToolNotFoundError(name)
        if actor_role not in definition.allowed_roles:
            raise ToolAuthorizationError(name)
        try:
            validated = definition.input_model.model_validate(arguments)
        except ValidationError as exc:
            raise ToolInputError(str(exc)) from exc
        return definition.handler(db, validated)

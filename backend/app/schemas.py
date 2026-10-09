from __future__ import annotations

from typing import Any, Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator


class PersonaCreate(BaseModel):
    slug: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9][a-z0-9_-]*$")
    name: str = Field(min_length=1, max_length=80)
    tagline: str = Field(default="", max_length=200)
    description: str = Field(default="", max_length=1000)
    avatar: str = Field(default="", max_length=500)
    accent: str = Field(default="#9e7b67", max_length=30)
    system_prompt: str = Field(default="", max_length=6000)
    traits: list[str] = Field(default_factory=list, max_length=20)


class SessionCreate(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    persona_id: str = Field(min_length=1, max_length=100, validation_alias=AliasChoices("persona_id", "personaId", "characterId"))
    title: str = Field(default="新的对话", max_length=120)


class MessageCreate(BaseModel):
    content: str = Field(min_length=1, max_length=12000)

    @field_validator("content")
    @classmethod
    def trim_content(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("content cannot be empty")
        return value


class MemoryCreate(BaseModel):
    content: str = Field(min_length=1, max_length=2000)
    category: str = Field(default="profile", min_length=1, max_length=40)
    importance: float = Field(default=0.5, ge=0, le=1)


class MessageResponse(BaseModel):
    session: dict[str, Any]
    user_message: dict[str, Any]
    assistant_message: dict[str, Any]
    memory_created: dict[str, Any] | None = None
    state: dict[str, Any] | None = None
    memories: list[dict[str, Any]] = Field(default_factory=list)
    promises: list[dict[str, Any]] = Field(default_factory=list)


class ProviderSettingsUpdate(BaseModel):
    base_url: str | None = Field(default=None, max_length=500)
    model: str | None = Field(default=None, max_length=200)
    api_key: str | None = Field(default=None, max_length=1000)


class HealthResponse(BaseModel):
    ok: bool
    provider: str
    llm_configured: bool
    database: str

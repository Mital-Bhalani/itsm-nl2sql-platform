"""Request and response models for the API (pydantic)."""

from typing import Any, Literal

from pydantic import BaseModel, Field


class HistoryTurn(BaseModel):
    """One earlier exchange, so a follow-up like 'and by priority?' has context."""
    question: str = Field(min_length=1, max_length=500)
    sql: str | None = Field(default=None, max_length=5000)


class AskRequest(BaseModel):
    question: str = Field(min_length=3, max_length=500)
    history: list[HistoryTurn] = Field(default=[], max_length=5,
                                       description="previous questions (and their SQL) of this conversation, newest last")
    provider: str | None = Field(default=None, description="openai or anthropic")
    model: str | None = Field(default=None, max_length=100)
    dataset: str = "default"
    answer: bool = Field(default=True, description="also write a plain-English answer")


class AskResponse(BaseModel):
    question: str
    answer: str | None
    followups: list[str] = []
    sql: str | None
    assumption: str | None
    refusal: str | None
    unsafe: str | None
    error: str | None
    terms: list[tuple[str, str]]
    columns: list[str]
    rows: list[list[Any]]
    row_count: int
    truncated: bool
    repaired: bool
    provider: str | None
    model: str | None
    tokens_in: int | None
    tokens_out: int | None
    timings: dict[str, int]
    request_id: str


class FeedbackRequest(BaseModel):
    request_id: str = Field(min_length=4, max_length=64)
    rating: Literal["up", "down"]
    question: str | None = Field(default=None, max_length=500)
    comment: str | None = Field(default=None, max_length=1000)


class SqlRequest(BaseModel):
    sql: str = Field(min_length=6, max_length=5000)
    dataset: str = "default"


class EvalRunRequest(BaseModel):
    golden: str = "golden_set.yaml"
    mode: Literal["self-test", "live"] = "self-test"
    provider: str | None = None
    model: str | None = Field(default=None, max_length=100)


class EvalJob(BaseModel):
    id: str
    status: Literal["queued", "running", "done", "failed"]
    mode: str
    golden: str
    provider: str | None
    model: str | None
    total: int
    completed: int
    passed: int
    execution_accuracy: float | None
    error: str | None
    started_at: str
    finished_at: str | None
    results: list[dict[str, Any]]

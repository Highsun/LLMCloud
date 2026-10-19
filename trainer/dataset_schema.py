"""CPU-only instruction record contract, shared by future upload/training readers."""

from pydantic import BaseModel, ConfigDict, field_validator


class InstructionRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    instruction: str
    input: str = ""
    output: str

    @field_validator("instruction", "output")
    @classmethod
    def require_nonblank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("必须是非空白字符串")
        # Check whitespace without rewriting training text.
        return value

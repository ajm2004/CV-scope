"""Frame source interface."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from pathscope.vision.types import FramePacket


class SourceError(RuntimeError):
    pass


@dataclass
class SourceInfo:
    source_type: str
    uri: str
    width: int
    height: int
    fps: float
    frame_count: int | None = None
    duration_s: float | None = None
    is_live: bool = False
    backend: str = ""

    def to_dict(self) -> dict:
        return self.__dict__.copy()


@dataclass
class ReconnectPolicy:
    enabled: bool = True
    initial_delay_s: float = 1.0
    max_delay_s: float = 30.0
    max_attempts: int = 0  # 0 = unlimited
    read_timeout_s: float = 10.0

    @classmethod
    def from_dict(cls, d: dict | None) -> ReconnectPolicy:
        d = d or {}
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


class FrameSource(ABC):
    source_type: str = "base"

    @abstractmethod
    def open(self) -> SourceInfo: ...

    @abstractmethod
    def read(self) -> FramePacket | None:
        """Return the next frame or None at end of stream."""

    @abstractmethod
    def close(self) -> None: ...

    @property
    @abstractmethod
    def info(self) -> SourceInfo: ...

    def seek(self, media_time_s: float) -> bool:  # pragma: no cover - default
        return False

    @property
    def is_live(self) -> bool:
        return self.info.is_live

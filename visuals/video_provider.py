"""
Finance Shorts Pro - Video Provider Base Abstraction
Defines the SceneVideoProvider base class and standard exceptions for scene video generation.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any


class VideoProviderError(Exception):
    """Base exception for video generation provider errors."""
    pass


class QuotaExceeded(VideoProviderError):
    """Raised when provider rate limit / resource quota is exceeded (non-retryable)."""
    pass


class ProviderTimeout(VideoProviderError):
    """Raised when an operation or scene generation times out."""
    pass


class BudgetCapReached(VideoProviderError):
    """Raised when estimated seconds/cost exceeds configured daily or per-run caps."""
    pass


class SceneVideoProvider(ABC):
    """Abstract base class for scene video generation providers."""

    @property
    @abstractmethod
    def supported_features(self) -> list[str]:
        """List of feature flags supported by this provider."""
        pass

    @abstractmethod
    def estimate_cost(self, scenes: list[dict[str, Any]]) -> dict[str, Any]:
        """
        Estimate duration and monetary cost for the given scenes before submission.
        Returns dict containing total_seconds, estimated_cost_usd, scenes_count, etc.
        """
        pass

    @abstractmethod
    def submit_scene(
        self,
        scene: dict[str, Any],
        index: int,
        job_dir: Path,
        topic_id: str = "",
    ) -> dict[str, Any]:
        """
        Submits an individual scene generation job to the remote API.
        Returns a job descriptor dict with operation metadata.
        """
        pass

    @abstractmethod
    def wait_scene(self, job: dict[str, Any]) -> Path:
        """
        Polls the generation job until completion, downloads the video,
        verifies and returns the local Path to the scene clip.
        """
        pass

    @abstractmethod
    def generate_all_scenes(
        self,
        scenes: list[dict[str, Any]],
        topic_id: str,
        output_dir: Path,
    ) -> list[Path]:
        """
        Orchestrates submitting all scenes first, checking budget caps,
        polling concurrently or in batch, and verifying all output files.
        """
        pass

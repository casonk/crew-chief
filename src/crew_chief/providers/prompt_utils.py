"""Backward-compatible re-export of shared prompt helpers."""

from crew_chief.prompt_utils import looks_like_embedded_transcript, wrap_literal_user_message

__all__ = ["looks_like_embedded_transcript", "wrap_literal_user_message"]

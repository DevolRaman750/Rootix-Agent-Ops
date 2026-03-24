"""Shared enum constants used across backend services.

This module centralizes canonical string values for span/trace statuses,
span kinds, and workspace member roles to keep API payloads and database
records consistent.
"""

from enum import StrEnum


class SpanKind(StrEnum):
    LLM = "LLM"
    AGENT = "AGENT"
    TOOL = "TOOL"
    SPAN = "SPAN"


class SpanStatus(StrEnum):
    OK = "OK"
    ERROR = "ERROR"


class TraceStatus(StrEnum):
    OK = "ok"
    ERROR = "error"


class MemberRole(StrEnum):
    VIEWER = "VIEWER"
    MEMBER = "MEMBER"
    ADMIN = "ADMIN"

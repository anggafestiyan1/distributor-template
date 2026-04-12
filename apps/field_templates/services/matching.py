"""Template matching service.

Scores TemplateVersions against a set of normalized headers and selects
the best matching template, following the priority order:
  1. Assigned templates for the distributor
  2. Global templates (fallback)
  3. None (mismatch)
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

from django.conf import settings

logger = logging.getLogger(__name__)


@dataclass
class MatchResult:
    template_version_id: int
    template_name: str
    version_number: int
    is_assigned: bool
    matched_count: int
    total_fields: int
    score: float  # matched / total_fields (0.0–1.0)
    matched_columns: list[str] = field(default_factory=list)
    unmatched_columns: list[str] = field(default_factory=list)
    reason: str = ""


@dataclass
class BestMatchResult:
    template_version: object | None  # TemplateVersion or None
    score: float
    used_global: bool
    fallback_happened: bool
    all_results: list[MatchResult] = field(default_factory=list)


def score_template_version(
    normalized_headers: list[str],
    template_version,
    alias_lookup: dict[str, int],
) -> MatchResult:
    """Score how well a TemplateVersion matches the given normalized headers.

    A header is considered "matched" for a field if:
      - The template mapping's source_column_normalized is in normalized_headers, OR
      - Any alias for that standard_field is in normalized_headers.

    Score = matched_required_fields / total_required_fields.
    If no required fields, score = matched_total / total_fields.
    """
    from apps.field_templates.models import TemplateFieldMapping

    mappings = list(
        TemplateFieldMapping.objects.filter(template_version=template_version)
        .select_related("standard_field")
    )

    if not mappings:
        return MatchResult(
            template_version_id=template_version.pk,
            template_name=str(template_version.template.name),
            version_number=template_version.version_number,
            is_assigned=template_version.template.scope == "assigned",
            matched_count=0,
            total_fields=0,
            score=0.0,
            reason="Template version has no field mappings",
        )

    headers_set = set(normalized_headers)
    matched_fields: set[str] = set()
    unmatched_fields: set[str] = set()

    for mapping in mappings:
        sf = mapping.standard_field
        if sf.name in matched_fields:
            continue  # Already matched by another mapping (alias) for same field

        is_matched = mapping.source_column_normalized in headers_set

        if is_matched:
            matched_fields.add(sf.name)
            unmatched_fields.discard(sf.name)
        elif sf.name not in matched_fields:
            unmatched_fields.add(sf.name)

    matched = list(matched_fields)
    unmatched = list(unmatched_fields)
    # Score = unique matched fields / unique fields in template
    unique_fields = matched_fields | unmatched_fields
    total_fields = len(unique_fields)
    score = len(matched_fields) / total_fields if total_fields > 0 else 0.0

    reason = _build_reason(score, [], matched, total_fields)

    return MatchResult(
        template_version_id=template_version.pk,
        template_name=str(template_version.template.name),
        version_number=template_version.version_number,
        is_assigned=template_version.template.scope == "assigned",
        matched_count=len(matched),
        total_fields=total_fields,
        score=score,
        matched_columns=matched,
        unmatched_columns=unmatched,
        reason=reason,
    )


def _build_reason(score: float, missing: list, matched: list, total_fields: int) -> str:
    if score >= 1.0:
        return f"All {total_fields} fields matched"
    return f"Matched {len(matched)} fields (score={score:.2f})"


def find_best_template(
    distributor,
    normalized_headers: list[str],
    alias_lookup: dict[str, int],
    min_score: float | None = None,
) -> BestMatchResult:
    """Find the best matching active TemplateVersion for a distributor.

    Matching order:
      1. Active assigned templates for the distributor (highest version first)
      2. Active global templates (fallback)

    Returns BestMatchResult with template_version=None if nothing scores above min_score.
    """
    from apps.field_templates.models import TemplateVersion

    if min_score is None:
        min_score = getattr(settings, "TEMPLATE_MATCH_MIN_SCORE", 0.8)

    all_results: list[MatchResult] = []

    # ── 1. Assigned templates ────────────────────────────────────────────────
    assigned_versions = list(
        TemplateVersion.objects.filter(
            template__scope="assigned",
            template__distributor=distributor,
            is_active=True,
        ).select_related("template")
        .order_by("-version_number")
    )

    best_assigned: MatchResult | None = None
    for version in assigned_versions:
        result = score_template_version(normalized_headers, version, alias_lookup)
        result.is_assigned = True
        all_results.append(result)
        if best_assigned is None or result.score > best_assigned.score:
            best_assigned = result

    if best_assigned and best_assigned.score >= min_score:
        winner = _get_version(best_assigned.template_version_id)
        logger.info(
            "Template match: assigned version %s score=%.2f",
            best_assigned.template_version_id,
            best_assigned.score,
        )
        return BestMatchResult(
            template_version=winner,
            score=best_assigned.score,
            used_global=False,
            fallback_happened=False,
            all_results=all_results,
        )

    # ── 2. Global templates (fallback) ───────────────────────────────────────
    global_versions = list(
        TemplateVersion.objects.filter(
            template__scope="global",
            is_active=True,
        ).select_related("template")
        .order_by("-version_number")
    )

    best_global: MatchResult | None = None
    for version in global_versions:
        result = score_template_version(normalized_headers, version, alias_lookup)
        result.is_assigned = False
        all_results.append(result)
        if best_global is None or result.score > best_global.score:
            best_global = result

    fallback = bool(assigned_versions)  # we tried assigned first

    if best_global and best_global.score >= min_score:
        winner = _get_version(best_global.template_version_id)
        logger.info(
            "Template match: global version %s score=%.2f (fallback=%s)",
            best_global.template_version_id,
            best_global.score,
            fallback,
        )
        return BestMatchResult(
            template_version=winner,
            score=best_global.score,
            used_global=True,
            fallback_happened=fallback,
            all_results=all_results,
        )

    # ── 3. No match ───────────────────────────────────────────────────────────
    logger.warning(
        "No template matched for distributor %s (min_score=%.2f)",
        distributor.pk,
        min_score,
    )
    return BestMatchResult(
        template_version=None,
        score=0.0,
        used_global=False,
        fallback_happened=fallback,
        all_results=all_results,
    )


def _get_version(pk: int):
    from apps.field_templates.models import TemplateVersion
    return TemplateVersion.objects.get(pk=pk)

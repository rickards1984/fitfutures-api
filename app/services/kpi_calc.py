"""KPI metric definitions + RAG calculation.

Single source of truth for the 9 KPI metrics (shared by the totals endpoint,
week submission, and the AI coach prompt) and the RAG logic. The thresholds
mirror the frontend `rag.ts` exactly so the API and UI never disagree.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class Metric:
    key: str
    label: str
    actual_col: str  # column on kpi_entries
    wk_target_col: str  # fixed weekly target column on placements
    total_target_col: str  # cumulative target column on placements
    # Conversions are tracked but excluded from the overall RAG roll-up
    # (their target defaults to 0, so they'd always read green).
    counts_for_rag: bool = True


METRICS: list[Metric] = [
    Metric("placement_hours", "Placement hours", "actual_placement_hours", "wk_target_placement_hours", "total_target_placement_hours"),
    Metric("study_hours", "Study hours", "actual_study_hours", "wk_target_study_hours", "total_target_study_hours"),
    Metric("member_conversations", "Member conversations", "actual_member_conversations", "wk_target_member_conversations", "total_target_member_conversations"),
    Metric("ex_member_contacts", "Ex-member contacts", "actual_ex_member_contacts", "wk_target_ex_member_contacts", "total_target_ex_member_contacts"),
    Metric("retention_saves", "Retention saves", "actual_retention_saves", "wk_target_retention_saves", "total_target_retention_saves"),
    Metric("campaign_touches", "Campaign touches", "actual_campaign_touches", "wk_target_campaign_touches", "total_target_campaign_touches"),
    Metric("tasters_booked", "Tasters booked", "actual_tasters_booked", "wk_target_tasters_booked", "total_target_tasters_booked"),
    Metric("consultations", "Consultations", "actual_consultations", "wk_target_consultations", "total_target_consultations"),
    Metric("conversions", "Conversions", "actual_conversions", "wk_target_conversions", "total_target_conversions", counts_for_rag=False),
]


def calc_rag(actual: float, target: float) -> str:
    """Per-metric RAG: green >=85%, amber >=50%, red below. Zero target = green."""
    if target == 0:
        return "green"
    pct = actual / target
    if pct >= 0.85:
        return "green"
    if pct >= 0.5:
        return "amber"
    return "red"


def week_overall_rag(entry: dict, placement: dict) -> str:
    """Worst-of roll-up across the RAG-counting metrics for one week."""
    rags = [
        calc_rag(float(entry.get(m.actual_col) or 0), float(placement.get(m.wk_target_col) or 0))
        for m in METRICS
        if m.counts_for_rag
    ]
    if "red" in rags:
        return "red"
    if "amber" in rags:
        return "amber"
    return "green"

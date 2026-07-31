"""Source registry: maps sources.yml 'kind' to implementation classes."""
from __future__ import annotations

from typing import Dict, Type

from .base import Source
from .workday import WorkdaySource
from .jibe import JibeSource
from .ats_simple import GreenhouseSource, LeverSource, SmartRecruitersSource
from .aggregators import AdzunaSource, JSearchSource, JoobleSource, USAJobsSource
from .ukg import UKGSource
from .travel import VivianSource, AyaSource
from .radancy import RadancySource, SitemapSource, AutoSource
from .boards import YMCareersSource, ICIMSClassicSource

REGISTRY: Dict[str, Type[Source]] = {
    cls.kind: cls
    for cls in [
        WorkdaySource, JibeSource,
        GreenhouseSource, LeverSource, SmartRecruitersSource,
        AdzunaSource, JSearchSource, JoobleSource, USAJobsSource,
        UKGSource, VivianSource, AyaSource,
        RadancySource, SitemapSource, AutoSource,
        YMCareersSource, ICIMSClassicSource,
    ]
}


def build_source(cfg: dict) -> Source:
    kind = cfg.get("kind")
    if kind not in REGISTRY:
        raise ValueError(f"unknown source kind: {kind!r} (source id: {cfg.get('id')!r})")
    return REGISTRY[kind](cfg)

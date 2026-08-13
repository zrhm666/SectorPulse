import asyncio, json
from datetime import datetime, timezone
from pathlib import Path
from pydantic import BaseModel, ConfigDict
from sector_pulse.domain.market import SectorKind
from sector_pulse.domain.provider import AuthorizationStatus
from sector_pulse.domain.quality import QualityReport, QualityStatus, QualityThresholds, evaluate_universe, lock_cutoff_from_core_market
from sector_pulse.domain.radar import build_diagnostic_radar
from sector_pulse.domain.time import AnalysisMode, AnalysisRun
from sector_pulse.ports.market_data import MarketDataPort
from sector_pulse.reporting.phase0_report import write_utf8_atomic
class Phase0ProbeReport(BaseModel):
    model_config=ConfigDict(frozen=True)
    run:AnalysisRun; provider_id:str; provider_version:str; provider_authorization:AuthorizationStatus; industry_source_version:str|None; concept_source_version:str|None; industry_quality:QualityReport; concept_quality:QualityReport; usable:bool
async def run_phase0_probe(provider:MarketDataPort,output_dir:Path,requested_at:datetime,thresholds:QualityThresholds,max_skew_seconds:int)->Phase0ProbeReport:
    run=AnalysisRun.create_live(requested_at); industry,concept=await asyncio.gather(provider.fetch_sector_universe(SectorKind.INDUSTRY,AnalysisMode.LIVE),provider.fetch_sector_universe(SectorKind.CONCEPT,AnalysisMode.LIVE)); iq,cq=evaluate_universe(industry,thresholds),evaluate_universe(concept,thresholds)
    report=Phase0ProbeReport(run=run,provider_id=provider.manifest.provider_id,provider_version=provider.manifest.version,provider_authorization=provider.manifest.authorization_status,industry_source_version=industry.source_version,concept_source_version=concept.source_version,industry_quality=iq,concept_quality=cq,usable=iq.status is not QualityStatus.BLOCKED and cq.status is not QualityStatus.BLOCKED)
    if not report.usable: write_utf8_atomic(output_dir/"probe.json",report.model_dump_json(indent=2)); return report
    assert industry.data is not None and concept.data is not None
    report=report.model_copy(update={"run":lock_cutoff_from_core_market(run,[industry,concept],datetime.now(timezone.utc),max_skew_seconds)})
    write_utf8_atomic(output_dir/"industry.json",industry.data.model_dump_json(indent=2)); write_utf8_atomic(output_dir/"concept.json",concept.data.model_dump_json(indent=2)); radar={"industry":[r.model_dump(mode="json") for r in build_diagnostic_radar(industry.data)[:20]],"concept":[r.model_dump(mode="json") for r in build_diagnostic_radar(concept.data)[:20]]}; write_utf8_atomic(output_dir/"radar.json",json.dumps(radar,ensure_ascii=False,indent=2)); write_utf8_atomic(output_dir/"probe.json",report.model_dump_json(indent=2)); return report

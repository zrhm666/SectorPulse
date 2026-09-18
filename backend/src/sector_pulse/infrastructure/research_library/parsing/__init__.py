"""解析适配器的装配点。

和 `assets/scanner.py` 的 `build_scanner` 一样，这里只做装配：选哪些实现、给它们什么
依赖。业务规则（谁该被解析、解析失败怎么办）属于调用方，不属于这里。
"""

from sector_pulse.application.research_library.parsing import ResearchParsePipeline
from sector_pulse.infrastructure.research_library.parsing.markdown import MarkdownDocumentParser
from sector_pulse.infrastructure.research_library.parsing.pdf import PdfDocumentParser
from sector_pulse.infrastructure.research_library.parsing.text import TextDocumentParser
from sector_pulse.ports.research_models import OcrProvider, ParseLimits


def build_parse_pipeline(
    *, ocr: OcrProvider | None = None, limits: ParseLimits | None = None
) -> ResearchParsePipeline:
    """构造覆盖 PDF、Markdown、TXT 的解析流水线。

    `ocr` 可以为 None：没有配置 OCR 时，需要 OCR 的页面会被记进 `warnings` 而不是
    被静默跳过——残缺的文档必须看起来像残缺的文档。
    """
    return ResearchParsePipeline(
        parsers=(
            PdfDocumentParser(ocr=ocr, limits=limits),
            MarkdownDocumentParser(),
            TextDocumentParser(),
        ),
        limits=limits,
    )

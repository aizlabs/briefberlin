"""Manual live eval for glossary hint generation.

This command calls the configured LLM. It is intended for local prompt tuning,
not normal CI.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
import time
from collections import Counter
from dataclasses import dataclass
from typing import Any

from scripts.config import load_config
from scripts.glossary_generator import GlossaryGenerator, StructuredOutputDegradedError
from scripts.logger import get_component_logger
from scripts.models import AdaptedArticle, VocabularyItem

BERLIN_HEAT_CONTENT = (
    "Ein heißes Wochenende steht Berlin bevor. Die Temperaturen könnten bis zu 41 Grad erreichen. "
    "Der Deutsche Wetterdienst sagt, dass der bisherige Rekord von 41,2 Grad aus dem Jahr 2019 "
    "vielleicht gebrochen wird. Diese Hitze zeigt, dass der Klimawandel real ist und uns direkt "
    "betrifft.\n\n"
    "Während die Temperaturen steigen, wird in Deutschland viel über Klimapolitik diskutiert. "
    "Die Regierung hat kürzlich Steuererleichterungen für Benzin und Diesel eingeführt. Diese "
    "Maßnahmen sind umstritten, weil sie die Erderwärmung verstärken könnten. Der sogenannte "
    "Tankrabatt und die niedrigeren Steuern auf Flugtickets kosten den Staat fast zwei Milliarden "
    "Euro. Kritiker sagen, dass vor allem Vielflieger und Autofahrer mit großen Autos davon "
    "profitieren.\n\n"
    "In Berlin fordern viele Menschen mehr Grünflächen und Schatten. Bäume in der Stadt können "
    "die Temperatur um bis zu 12 Grad senken. Ein Gesetz in Berlin plant, bis 2040 eine Million "
    "Bäume zu pflanzen. Doch es gibt Probleme mit der Finanzierung, weil das Geld dafür halbiert "
    "wurde. Städte, die sich gut auf den Klimawandel vorbereiten, könnten Vorteile haben.\n\n"
    "Um mit der Hitze umzugehen, braucht es nicht nur neue Infrastruktur, sondern auch ein "
    "Umdenken. Die hohen Temperaturen haben wirtschaftliche Folgen. Ein Tag mit über 30 Grad "
    "kostet die deutsche Wirtschaft laut Experten 431 Millionen Euro. Deutschland muss den "
    "Klimawandel ernst nehmen und Maßnahmen ergreifen, um seine Städte widerstandsfähiger zu "
    "machen."
)

BERLIN_HEAT_EXPECTED_TERMS = [
    "steht Berlin bevor",
    "erreichen",
    "bisherige",
    "betrifft",
    "Klimapolitik",
    "Steuererleichterungen",
    "eingeführt",
    "umstritten",
    "Vielflieger",
    "Erderwärmung",
    "Grünflächen",
    "Schatten",
    "senken",
    "pflanzen",
    "vorbereiten",
    "Vorteile",
    "umzugehen",
    "widerstandsfähiger",
]


@dataclass(frozen=True)
class EvalFixture:
    slug: str
    title: str
    level: str
    content: str
    expected_terms: list[str]


FIXTURES = {
    "berlin-heat": EvalFixture(
        slug="berlin-heat",
        title="Berlin bereitet sich auf extreme Hitze vor",
        level="B1",
        content=BERLIN_HEAT_CONTENT,
        expected_terms=BERLIN_HEAT_EXPECTED_TERMS,
    )
}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run a manual live LLM eval for glossary hint generation.",
    )
    parser.add_argument("--fixture", choices=sorted(FIXTURES), default="berlin-heat")
    parser.add_argument("--environment", default=os.getenv("ENVIRONMENT", "local"))
    parser.add_argument("--provider", default=os.getenv("GLOSSARY_EVAL_PROVIDER"))
    parser.add_argument("--model", default=os.getenv("GLOSSARY_EVAL_MODEL"))
    parser.add_argument("--base-url", default=os.getenv("GLOSSARY_EVAL_BASE_URL"))
    parser.add_argument("--min-accepted", type=int, default=20)
    parser.add_argument("--min-expected-recall", type=float, default=0.6)
    parser.add_argument("--min-standalone-ratio", type=float, default=0.6)
    parser.add_argument("--max-overlong-accepted", type=int, default=0)
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON only")
    parser.add_argument("--list-fixtures", action="store_true")
    return parser.parse_args(argv)


def _progress(message: str) -> None:
    """Print a progress line to stderr so stdout stays clean for --json output."""
    print(f"• {message}", file=sys.stderr, flush=True)


def apply_preload_env_overrides(args: argparse.Namespace) -> None:
    """Map eval-specific overrides to normal config env vars before load_config()."""
    if args.provider:
        os.environ["LLM_PROVIDER"] = args.provider
    if args.base_url:
        os.environ["LLM_BASE_URL"] = args.base_url
    if args.model:
        os.environ["LLM_ADAPTATION_MODEL"] = args.model


def build_article(fixture: EvalFixture) -> AdaptedArticle:
    return AdaptedArticle(
        title=fixture.title,
        content=fixture.content,
        summary="Live glossary evaluation fixture.",
        reading_time=3,
        level=fixture.level,
    )


def token_count(term: str) -> int:
    return len(re.findall(r"\w+", term, flags=re.UNICODE))


def compute_metrics(
    *,
    fixture: EvalFixture,
    generated: list[VocabularyItem],
    accepted: list[VocabularyItem],
    dropped: dict[str, str],
    visible_glossary: list[VocabularyItem],
) -> dict[str, Any]:
    accepted_terms = [item.term for item in accepted]
    accepted_keys = {term.casefold() for term in accepted_terms}
    expected_found = [term for term in fixture.expected_terms if term.casefold() in accepted_keys]
    expected_missing = [
        term for term in fixture.expected_terms
        if term.casefold() not in accepted_keys
    ]
    standalone_terms = [term for term in accepted_terms if token_count(term) == 1]
    overlong_terms = [term for term in accepted_terms if token_count(term) > 3]
    default_terms = [item.term for item in visible_glossary]

    expected_recall = len(expected_found) / len(fixture.expected_terms)
    standalone_ratio = len(standalone_terms) / len(accepted_terms) if accepted_terms else 0.0

    return {
        "fixture": fixture.slug,
        "level": fixture.level,
        "generated_candidates": len(generated),
        "accepted_hints": len(accepted),
        "default_glossary": len(visible_glossary),
        "rejected": len(dropped),
        "standalone_ratio": round(standalone_ratio, 3),
        "overlong_accepted": len(overlong_terms),
        "expected_recall": round(expected_recall, 3),
        "accepted_terms": accepted_terms,
        "default_terms": default_terms,
        "expected_found": expected_found,
        "expected_missing": expected_missing,
        "overlong_terms": overlong_terms,
        "dropped": dropped,
    }


def evaluate_thresholds(metrics: dict[str, Any], args: argparse.Namespace) -> list[str]:
    failures: list[str] = []
    if metrics["accepted_hints"] < args.min_accepted:
        failures.append(
            f"accepted_hints {metrics['accepted_hints']} < min_accepted {args.min_accepted}"
        )
    if metrics["expected_recall"] < args.min_expected_recall:
        failures.append(
            f"expected_recall {metrics['expected_recall']} < "
            f"min_expected_recall {args.min_expected_recall}"
        )
    if metrics["standalone_ratio"] < args.min_standalone_ratio:
        failures.append(
            f"standalone_ratio {metrics['standalone_ratio']} < "
            f"min_standalone_ratio {args.min_standalone_ratio}"
        )
    if metrics["overlong_accepted"] > args.max_overlong_accepted:
        failures.append(
            f"overlong_accepted {metrics['overlong_accepted']} > "
            f"max_overlong_accepted {args.max_overlong_accepted}"
        )
    return failures


def print_report(
    *,
    provider: str,
    model: str,
    base_url: str | None,
    metrics: dict[str, Any],
    failures: list[str],
) -> None:
    print(f"Fixture: {metrics['fixture']}")
    print(f"Level: {metrics['level']}")
    print(f"Provider: {provider}")
    print(f"Model: {model}")
    if base_url:
        print(f"Base URL: {base_url}")
    print()
    print(f"Generated candidates: {metrics['generated_candidates']}")
    print(f"Accepted hints: {metrics['accepted_hints']}")
    print(f"Default glossary: {metrics['default_glossary']}")
    print(f"Rejected: {metrics['rejected']}")
    print()
    print(f"Standalone ratio: {metrics['standalone_ratio']}")
    print(f"Overlong accepted phrases: {metrics['overlong_accepted']}")
    print(f"Expected recall: {metrics['expected_recall']}")
    print()
    print("Default glossary terms:")
    for term in metrics["default_terms"]:
        print(f"- {term}")
    print()
    print("Expected terms found:")
    for term in metrics["expected_found"]:
        print(f"- {term}")
    print()
    print("Expected terms missing:")
    for term in metrics["expected_missing"]:
        print(f"- {term}")

    if metrics["overlong_terms"]:
        print()
        print("Overlong accepted terms:")
        for term in metrics["overlong_terms"]:
            print(f"- {term}")

    if failures:
        print()
        print("Threshold failures:")
        for failure in failures:
            print(f"- {failure}")


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.list_fixtures:
        for fixture_name in sorted(FIXTURES):
            print(fixture_name)
        return 0

    apply_preload_env_overrides(args)
    config = load_config(args.environment)
    fixture = FIXTURES[args.fixture]
    article = build_article(fixture)

    logger = get_component_logger("eval_glossary_llm", config)
    logging.basicConfig(level=logging.WARNING)

    model_name = config.llm.models.adaptation or config.llm.models.generation
    endpoint = f" | base_url: {config.llm.base_url}" if config.llm.base_url else ""
    _progress(f"Fixture: {fixture.slug} (level {fixture.level})")
    _progress(f"Provider: {config.llm.provider} | model: {model_name}{endpoint}")

    generator = GlossaryGenerator(config, logger)
    _progress("Calling the LLM to generate glossary candidates (can take 10-60s locally)...")
    start = time.time()
    try:
        generated = generator.generate(article)
    except StructuredOutputDegradedError as exc:
        _progress(f"Error: {exc}")
        if args.json:
            print(
                json.dumps(
                    {
                        "provider": config.llm.provider,
                        "model": model_name,
                        "base_url": config.llm.base_url,
                        "error": {
                            "type": "StructuredOutputDegradedError",
                            "mode": exc.mode,
                            "message": str(exc),
                        },
                        "metrics": {
                            "fixture": fixture.slug,
                            "level": fixture.level,
                            "generated_candidates": 0,
                            "accepted_hints": 0,
                            "default_glossary": 0,
                            "rejected": 0,
                            "standalone_ratio": 0.0,
                            "overlong_accepted": 0,
                            "expected_recall": 0.0,
                            "accepted_terms": [],
                            "default_terms": [],
                            "expected_found": [],
                            "expected_missing": fixture.expected_terms,
                            "overlong_terms": [],
                            "dropped": {},
                        },
                        "failures": ["structured glossary output degraded"],
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
        else:
            print(f"\nError: {exc}\n", file=sys.stderr)
        return 1
    _progress(f"Generated {len(generated)} candidates in {time.time() - start:.1f}s")
    if generated:
        _progress("Sample candidates: " + ", ".join(item.term for item in generated[:8]))

    accepted, dropped = generator.validate(article.content, generated)
    _progress(f"Validation: accepted {len(accepted)}, dropped {len(dropped)}")
    if dropped:
        reasons = Counter(dropped.values())
        _progress(
            "Drop reasons: "
            + ", ".join(f"{reason}={count}" for reason, count in reasons.most_common())
        )

    visible_glossary = generator.select_default_glossary(article.level, accepted)
    _progress(f"Default glossary selected: {len(visible_glossary)} entries")

    metrics = compute_metrics(
        fixture=fixture,
        generated=generated,
        accepted=accepted,
        dropped=dropped,
        visible_glossary=visible_glossary,
    )
    failures = evaluate_thresholds(metrics, args)

    if metrics["accepted_hints"] == 0:
        print(
            "\nWarning: Zero glossary hints were accepted. This is often the signature of a model "
            "that struggles with strict tool-calling structured output (e.g. returning candidate terms "
            "that are not actually present in the source article text). Suggest trying a tool-capable "
            "model such as qwen2.5.\n",
            file=sys.stderr,
        )

    if args.json:
        print(
            json.dumps(
                {
                    "provider": config.llm.provider,
                    "model": model_name,
                    "base_url": config.llm.base_url,
                    "metrics": metrics,
                    "failures": failures,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        print_report(
            provider=config.llm.provider,
            model=model_name,
            base_url=config.llm.base_url,
            metrics=metrics,
            failures=failures,
        )

    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())

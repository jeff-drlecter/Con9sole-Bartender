"""Replay reviewed public FC 27 examples offline. No credentials, URLs fetched or messages sent."""
from __future__ import annotations

import argparse
import asyncio
from contextlib import asynccontextmanager
from dataclasses import asdict
import json
from pathlib import Path
import sys
import tempfile
import time
import tracemalloc

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.fc27_updates import Article, HUB, NEWS, PreviewLedger, poll_indexes
from core.sqlite_storage import connect_sqlite


def examples():
    # Synthetic short briefs; only metadata/links refer to actual official articles.
    v12 = Article(NEWS + "fc27-title-update-v1-2-0", "EA SPORTS FC™ 27 | Title Update v1.2.0",
                  "Defensive positioning changes.", "EA SPORTS")
    v12_hub = Article(HUB + "ea-sports-fc%E2%84%A2-27--title-update-v1-2/13860352",
                      "EA SPORTS FC™ 27 | Title Update v1.2", v12.brief, "EA_Vendcera", "Community Manager")
    pitch = Article(NEWS + "update-v1-3-pitch-notes", "EA SPORTS FC™ 27 | Title Update v1.3.0 Pitch Notes",
                    "Taller players turn more easily in tight spaces. The Grounds matchmaking also changes.",
                    "EA SPORTS", demo_text="The player shown in this video")
    mirror = Article(HUB + "ea-sports-fc%E2%84%A2-27--title-update-v1-3-0-pitch-notes/13897390",
                     pitch.title, pitch.brief, "EA_Vendcera", "Community Manager", canonical=pitch.url)
    patch = Article(HUB + "ea-sports-fc%E2%84%A2-27--title-update-v1-3-0/13897645",
                    "EA SPORTS FC™ 27 | Title Update v1.3.0",
                    "Goalkeepers cover the near post more reliably. Shots from tight angles have more spread.",
                    "EA_Vendcera", "Community Manager")
    return v12, v12_hub, pitch, mirror, patch


def preview(path, *, source_only=False):
    v12, v12_hub, pitch, mirror, patch = examples()
    ledger = PreviewLedger(path)
    async def replay():
        for hour in range(3):
            indexes = ({"news": [v12], "hub": [v12_hub]} if hour == 0 else
                       {"news": [v12, pitch], "hub": [v12_hub, mirror, patch]})

            @asynccontextmanager
            async def open_fixture(source):
                async def chunks():
                    yield json.dumps([asdict(item) for item in indexes[source]]).encode()
                yield chunks()

            def parse_fixture(source, body):
                return [Article(**fields) for fields in json.loads(body)]

            await poll_indexes(ledger, 1_795_651_200 + hour * 3600, open_fixture, parse_fixture)

    asyncio.run(replay())
    translations = {
        pitch.brief: "高大球員在狹窄空間轉向更靈活，The Grounds 的配對機制也有調整。",
        patch.brief: "守門員防守近柱更穩定，小角度射門的落點會較分散。",
    }
    calls = 0
    while job := ledger.claim(1_795_651_200):
        identity, brief = job
        calls += 1
        ledger.finish(identity, None if source_only else translations[brief])
    with connect_sqlite(path) as db:
        reserved = db.execute("SELECT COALESCE(SUM(characters),0) FROM usage").fetchone()[0]
    return ledger.cards(), calls, reserved


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-only", action="store_true", help="simulate translation provider unavailable")
    parser.add_argument("--metrics", action="store_true", help="also print local measurements")
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="fc27-preview-") as tmp:
        tracemalloc.start()
        started = time.perf_counter()
        cards, calls, reserved = preview(Path(tmp) / "translation.sqlite3", source_only=args.source_only)
        elapsed = time.perf_counter() - started
        _, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
    print("\n\n".join(cards))
    if args.metrics:
        print(f"\nOffline: {len(cards)} cards, {calls} translator stand-in calls, {reserved} reserved characters, "
              f"0 HTTP bytes, {elapsed * 1000:.1f} ms, {peak:,} peak traced Python bytes.")


if __name__ == "__main__":
    main()

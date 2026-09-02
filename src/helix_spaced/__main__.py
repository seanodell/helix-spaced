import argparse
import sys

from .deck import load_dir, validate
from .store import Store


def cmd_train(args) -> int:
    from .app import run
    run(limit=args.limit)
    return 0


def cmd_validate(args) -> int:
    cards = load_dir()
    problems = validate(cards)
    for p in problems:
        print(f"FAIL {p}")
    print(f"{len(cards)} cards, {len(problems)} problems")
    return 1 if problems else 0


def cmd_stats(args) -> int:
    store = Store()
    cards = {c.id: c for c in load_dir()}
    s = store.stats()
    pct = (100 * s["solved"] / s["reviews"]) if s["reviews"] else 0
    print(f"reviews {s['reviews']}   solved {s['solved']} ({pct:.0f}%)   "
          f"avg {s['avg_ms'] / 1000:.1f}s")
    hard = store.hardest()
    if hard:
        print("\nhardest cards")
        for row in hard:
            card = cards.get(row["id"])
            label = card.prompt if card else row["id"]
            print(f"  {row['penalty_ewma']:.2f}  {row['id']:<28} {label[:48]}")
    store.close()
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="helix-spaced")
    sub = p.add_subparsers(dest="cmd")

    t = sub.add_parser("train", help="run a training session (default)")
    t.add_argument("-n", "--limit", type=int, default=None, help="stop after N cards")
    t.set_defaults(func=cmd_train)

    sub.add_parser("validate", help="check every card is solvable").set_defaults(
        func=cmd_validate)
    sub.add_parser("stats", help="review history and hardest cards").set_defaults(
        func=cmd_stats)

    args = p.parse_args(argv)
    if not getattr(args, "func", None):
        args = p.parse_args((argv or []) + ["train"])
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())

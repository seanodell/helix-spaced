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


def cmd_keys(args) -> int:
    from .keycheck import run
    run()
    return 0


def cmd_stats(args) -> int:
    from .deck import sections as split_sections
    store = Store()
    all_cards = load_dir()
    cards = {c.id: c for c in all_cards}
    s = store.stats()
    pct = (100 * s["solved"] / s["reviews"]) if s["reviews"] else 0
    print(f"reviews {s['reviews']}   solved {s['solved']} ({pct:.0f}%)   "
          f"avg {s['avg_ms'] / 1000:.1f}s")
    mastered = store.mastered_ids() & set(cards)
    secs = split_sections(all_cards)
    done_secs = [s for s in secs if all(c.id in mastered for c in s.cards)]
    print(f"mastered {len(mastered)}/{len(cards)} cards, "
          f"{len(done_secs)}/{len(secs)} sections")
    current = next((s for s in secs
                    if not all(c.id in mastered for c in s.cards)), None)
    print("\ncurriculum")
    for sec in secs:
        n = sum(1 for c in sec.cards if c.id in mastered)
        if n == len(sec.cards):
            mark = "done   "
        elif current is not None and sec.order == current.order:
            mark = "current"
        else:
            mark = "locked "
        bar = "#" * n + "." * (len(sec.cards) - n)
        print(f"  {sec.order:>2}. {mark} {sec.title:<28} {bar:<16} {n}/{len(sec.cards)}")
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
    sub.add_parser("keys", help="show what your terminal sends for each key").set_defaults(
        func=cmd_keys)

    args = p.parse_args(argv)
    if not getattr(args, "func", None):
        args = p.parse_args((argv or []) + ["train"])
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())

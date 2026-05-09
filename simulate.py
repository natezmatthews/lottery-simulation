#!/usr/bin/env python3
"""
Ticket lottery wave simulation (deterministic, aggregate redemption).

Rounding: always rounded down for redemption share, split among redeemers, and new-offer issuance (half-gap).
See footnote in HTML output.
"""

from __future__ import annotations

import argparse
import csv
import math
import sys
from dataclasses import dataclass
from typing import List, Sequence


def floor_pct(rate: float, n: int) -> int:
    """Deterministic aggregate application of a percentage (rounded down to an integer)."""
    if n <= 0:
        return 0
    return int(math.floor(rate * n))


@dataclass
class DayRow:
    day: int
    expired_removed: int
    outstanding_start: int
    redeem_offers: int
    redeem_1_ticket: int
    redeem_2_ticket: int
    tickets_sold_day: int
    cumulative_tickets_sold: int
    max_sellable_after_redemptions: int
    gap_before_issue: int
    new_offers_issued: int
    outstanding_end: int


def simulate(
    target_tickets: int,
    redemption_rate: float,
    two_ticket_share: float,
    offer_valid_days: int,
    initial_offers: int | None = None,
    max_days: int = 500,
) -> tuple[List[DayRow], dict]:
    """
    Each offer has issue_day d; valid while current_day <= d + offer_valid_days - 1
    (offer_valid_days consecutive calendar days including issue day).
    """
    if target_tickets <= 0:
        raise ValueError("target_tickets must be positive")
    if not (0 < redemption_rate <= 1):
        raise ValueError("redemption_rate must be in (0, 1]")
    if not (0 < two_ticket_share <= 1):
        raise ValueError("two_ticket_share must be in (0, 1]")
    if initial_offers is None:
        initial_offers = target_tickets // 2

    # offers: issue_day for each outstanding offer (unordered; we sort when needed)
    offers: List[int] = [1] * initial_offers

    cumulative_sold = 0
    rows: List[DayRow] = []
    meta = {
        "stopped_reason": "max_days",
        "initial_offers": initial_offers,
        "target_tickets": target_tickets,
    }

    for day in range(1, max_days + 1):
        outstanding_start = len(offers)

        # 1) Remove expired (not valid on `day`)
        last_valid_day = lambda issue: issue + offer_valid_days - 1
        expired_removed = 0
        kept: List[int] = []
        for issue in offers:
            if day <= last_valid_day(issue):
                kept.append(issue)
            else:
                expired_removed += 1
        offers = kept

        # 2) Redeem aggregate share (rounded down). If the pool is tiny, that can be 0 while
        # offers still exist; redeem at least 1 offer when any remain so the run can
        # converge (documented in HTML footnote).
        n_out = len(offers)
        redeem_offers = floor_pct(redemption_rate, n_out)
        redeem_offers = min(redeem_offers, n_out)
        if n_out > 0 and redeem_offers == 0:
            redeem_offers = 1

        # Prefer redeeming offers that expire soonest (smallest last_valid_day)
        idx_sorted = sorted(
            range(len(offers)),
            key=lambda i: (offers[i] + offer_valid_days - 1, offers[i], i),
        )
        redeem_set = set(idx_sorted[:redeem_offers])
        new_pool: List[int] = [offers[i] for i in range(len(offers)) if i not in redeem_set]

        two_buy = floor_pct(two_ticket_share, redeem_offers)
        one_buy = redeem_offers - two_buy
        tickets_sold_day = 2 * two_buy + one_buy
        cumulative_sold += tickets_sold_day

        max_after = cumulative_sold + 2 * len(new_pool)
        gap = target_tickets - max_after
        new_offers = gap // 2 if gap > 0 else 0
        # If only one ticket of headroom remains, gap/2 rounded down is 0; issue one offer so the
        # run can finish (remainder slack; footnote in HTML).
        if gap > 0 and new_offers == 0:
            new_offers = 1
        for _ in range(new_offers):
            new_pool.append(day)

        offers = new_pool
        outstanding_end = len(offers)

        rows.append(
            DayRow(
                day=day,
                expired_removed=expired_removed,
                outstanding_start=outstanding_start,
                redeem_offers=redeem_offers,
                redeem_1_ticket=one_buy,
                redeem_2_ticket=two_buy,
                tickets_sold_day=tickets_sold_day,
                cumulative_tickets_sold=cumulative_sold,
                max_sellable_after_redemptions=max_after,
                gap_before_issue=gap,
                new_offers_issued=new_offers,
                outstanding_end=outstanding_end,
            )
        )

        if cumulative_sold >= target_tickets:
            meta["stopped_reason"] = "target_reached"
            break

        if redeem_offers == 0 and new_offers == 0 and len(offers) == 0:
            meta["stopped_reason"] = "deadlock_no_offers"
            break

    return rows, meta


def format_table(rows: Sequence[DayRow]) -> str:
    headers = [
        "Day",
        "Expired",
        "Out₀",
        "Redeem",
        "1tk",
        "2tk",
        "Tk/day",
        "Σ Tk",
        "Ceiling",
        "Gap",
        "New",
        "Out₁",
    ]
    lines = [" | ".join(headers), "-" * (len(" | ".join(headers)))]
    for r in rows:
        line = " | ".join(
            str(x)
            for x in (
                r.day,
                r.expired_removed,
                r.outstanding_start,
                r.redeem_offers,
                r.redeem_1_ticket,
                r.redeem_2_ticket,
                r.tickets_sold_day,
                r.cumulative_tickets_sold,
                r.max_sellable_after_redemptions,
                r.gap_before_issue,
                r.new_offers_issued,
                r.outstanding_end,
            )
        )
        lines.append(line)
    return "\n".join(lines)


def rows_to_csv(rows: Sequence[DayRow], out) -> None:
    w = csv.writer(out)
    w.writerow(
        [
            "day",
            "expired_removed",
            "outstanding_start",
            "redeem_offers",
            "redeemed_1_ticket",
            "redeemed_2_ticket",
            "tickets_sold_day",
            "cumulative_tickets_sold",
            "ceiling_tickets_after_redemptions",
            "gap_before_issue",
            "new_offers_issued",
            "outstanding_end",
        ]
    )
    for r in rows:
        w.writerow(
            [
                r.day,
                r.expired_removed,
                r.outstanding_start,
                r.redeem_offers,
                r.redeem_1_ticket,
                r.redeem_2_ticket,
                r.tickets_sold_day,
                r.cumulative_tickets_sold,
                r.max_sellable_after_redemptions,
                r.gap_before_issue,
                r.new_offers_issued,
                r.outstanding_end,
            ]
        )


def main(argv: List[str]) -> int:
    p = argparse.ArgumentParser(description="Lottery offer wave simulation")
    p.add_argument("--tickets", type=int, default=1000, help="Target tickets to sell")
    p.add_argument("--redemption", type=float, default=0.8, help="Share of outstanding offers redeemed per day")
    p.add_argument("--two-share", type=float, default=0.8, help="Share of redeemers who buy 2 tickets")
    p.add_argument("--valid-days", type=int, default=5, help="Consecutive days each offer is valid (including issue day)")
    p.add_argument("--initial-offers", type=int, default=None, help="Override initial offer count (default tickets//2)")
    p.add_argument("--csv", type=str, default=None, help="Write CSV to path")
    args = p.parse_args(argv)

    rows, meta = simulate(
        target_tickets=args.tickets,
        redemption_rate=args.redemption,
        two_ticket_share=args.two_share,
        offer_valid_days=args.valid_days,
        initial_offers=args.initial_offers,
    )

    print(format_table(rows))
    print()
    print(
        "Meta:",
        f"stopped={meta['stopped_reason']}",
        f"initial_offers={meta['initial_offers']}",
        f"target={meta['target_tickets']}",
    )

    if args.csv:
        with open(args.csv, "w", newline="", encoding="utf-8") as f:
            rows_to_csv(rows, f)
        print(f"Wrote {args.csv}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

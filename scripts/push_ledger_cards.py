#!/usr/bin/env python3
"""One-way push of claim report cards into the vault.

Renders each claim via ledger.render_claim_card and PUTs it to
宏观经济/_pipeline/_ledger/<clm_id>.md through the Obsidian Local REST API
(bypasses macOS TCC). The vault is display/delivery only - it never writes
back to the ledger. Run after seeding or whenever a claim's state changes.

Usage:
  python3 scripts/push_ledger_cards.py            # all claims
  python3 scripts/push_ledger_cards.py clm_xxx     # one claim
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lib"))

import store
import ledger
import vault_writer


def main():
    target = sys.argv[1] if len(sys.argv) > 1 else None
    try:
        vw = vault_writer.VaultWriter()
    except Exception as e:
        print(f"vault writer init failed: {e}")
        print("Is Obsidian running with the Local REST API plugin enabled?")
        return 1

    conn = store._connect()
    if target:
        claims = [(target,)]
    else:
        claims = conn.execute("SELECT clm_id FROM claim ORDER BY created_at").fetchall()

    pushed = 0
    for (clm_id,) in claims:
        card = ledger.render_claim_card(conn, clm_id)
        if card.startswith("<!--"):
            print(f"  skip {clm_id}: claim not found")
            continue
        rel = f"_ledger/{clm_id}.md"
        try:
            vw.put_pipeline(rel, card)
            stmt = conn.execute("SELECT statement FROM claim WHERE clm_id=?",
                                (clm_id,)).fetchone()[0][:30]
            print(f"  pushed {clm_id} -> 宏观经济/_pipeline/{rel}  ({stmt})")
            pushed += 1
        except Exception as e:
            print(f"  FAILED {clm_id}: {e}")
    print(f"done: {pushed}/{len(claims)} claim cards pushed")
    return 0 if pushed else 2


if __name__ == "__main__":
    sys.exit(main())

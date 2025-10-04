from typing import Optional
from aqt import mw
from aqt.qt import QAction, QInputDialog, QMessageBox
from aqt.browser import Browser
from aqt.reviewer import Reviewer
from aqt.utils import tooltip
from anki.hooks import addHook

import sqlite3
import random
import os
import time

# Path to user_files folder
ADDON_DIR = os.path.dirname(__file__)
ADDON_USER_FILES_DIR = os.path.join(ADDON_DIR, "user_files")
os.makedirs(ADDON_USER_FILES_DIR, exist_ok=True)

DB_PATH = os.path.join(ADDON_USER_FILES_DIR, "bury.db")


def init_db() -> None:
    """Ensure database exists with correct schema."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS buried (
            cid INTEGER PRIMARY KEY,
            until INTEGER
        )
    """)
    conn.commit()
    conn.close()


def parse_days_range(text: str) -> Optional[tuple[int, int]]:
    """Parse input as either a single number or a range, return (low, high)."""
    text = text.strip()
    if "-" in text:
        try:
            low, high = text.split("-", 1)
            low_val, high_val = int(low), int(high)
            if low_val > high_val:
                return None
        except ValueError:
            return None
    else:
        val = int(text)
        low_val, high_val = val, val

    if low_val < 1:
        return None

    return low_val, high_val


def mark_cards_as_n_buried(cids: list[int], days_range: tuple[int, int]) -> None:
    """Mark cards as buried for random number of days in [low, high]."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    for cid in cids:
        days = random.randint(days_range[0], days_range[1])
        until_ts = int(time.time() + days * 86400)
        c.execute(
            "INSERT OR REPLACE INTO buried (cid, until) VALUES (?, ?)", (cid, until_ts)
        )
    conn.commit()
    conn.close()


def ask_days_range(parent) -> Optional[tuple[int, int]]:
    """Ask user for bury days input until valid or canceled."""
    days_range: Optional[tuple[int, int]] = None
    while days_range is None:
        text, ok = QInputDialog.getText(
            parent, "Bury N days", "Enter number of days (e.g. '10' or '1-100'):"
        )
        if not ok or not text.strip():
            return None
        days_range = parse_days_range(text)
        if days_range is None:
            QMessageBox.warning(
                parent,
                "Bury N days",
                "Invalid input. Please enter a number or range like '1-100'.",
            )
    return days_range


def bury_cards_ui(parent, cids: list[int]) -> None:
    """Shared UI logic for burying given card IDs."""
    if not cids:
        QMessageBox.information(parent, "Bury N days", "No cards selected.")
        return

    days_range = ask_days_range(parent)
    if not days_range:
        return

    mark_cards_as_n_buried(cids, days_range)
    mw.col.sched.buryCards(cids)

    if days_range[0] == days_range[1]:
        tooltip("Buried {} card(s) for {} days.".format(len(cids), days_range[0]))
    else:
        tooltip(
            "Buried {} card(s) for {} to {} days.".format(
                len(cids), days_range[0], days_range[1]
            )
        )


def bury_browser_selected(browser: Browser) -> None:
    """Triggered from Browser context menu."""
    bury_cards_ui(browser, browser.selectedCards())


def bury_reviewer_card(reviewer: Reviewer) -> None:
    """Triggered from Reviewer 'More' menu."""
    if reviewer.card:
        bury_cards_ui(mw, [reviewer.card.id])


def add_context_menu(browser: Browser) -> None:
    """Add 'Bury N days' option to Browser context menu."""
    action = QAction("Bury N days", browser)
    action.triggered.connect(lambda _, b=browser: bury_browser_selected(b))
    browser.form.menu_Cards.addAction(action)


def add_reviewer_menu(view: Reviewer, menu) -> None:
    """Add 'Bury N days' option to Reviewer More menu, above the first separator."""
    action = QAction("Bury N days", menu)
    action.triggered.connect(lambda _, r=view: bury_reviewer_card(r))

    # Find the first separator
    actions = menu.actions()
    inserted = False
    for act in actions:
        if act.isSeparator():
            menu.insertAction(act, action)
            inserted = True
            break

    if not inserted:
        # fallback if no separator found → just append
        menu.addAction(action)


def cleanup_expired(conn: sqlite3.Connection) -> None:
    """Remove expired entries."""
    now = int(time.time())
    c = conn.cursor()
    c.execute("DELETE FROM buried WHERE until <= ?", (now,))
    conn.commit()
    conn.close()


def reapply_buries() -> None:
    """At Anki startup, re-bury still-active cards."""
    now = int(time.time())
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT cid FROM buried WHERE until > ?", (now,))
    rows = c.fetchall()

    if rows:
        cids = [cid for (cid,) in rows]
        op_result = mw.col.sched.buryCards(cids)
        tooltip("Re-buried {} of {} cards.".format(op_result.count, len(cids)))

    # cleanup
    if random.randint(1, 10) == 1:
        cleanup_expired(conn)

    conn.close()


# Initialize
init_db()
addHook("browser.setupMenus", add_context_menu)
addHook("profileLoaded", reapply_buries)

try:
    from aqt import gui_hooks

    def on_sync_will_start(*_) -> None:
        reapply_buries()

    def on_sync_finished(*_) -> None:
        reapply_buries()

    gui_hooks.sync_will_start.append(on_sync_will_start)
    gui_hooks.sync_did_finish.append(on_sync_finished)
    gui_hooks.reviewer_will_show_context_menu.append(add_reviewer_menu)

except ImportError:
    # very old Anki, no gui_hooks
    pass

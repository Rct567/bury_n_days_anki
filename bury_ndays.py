from functools import partial
import json
import pprint
from typing import Any, Optional, Union
from aqt import QMenu, mw
from aqt.qt import QAction, QInputDialog, QMessageBox
from aqt.browser import Browser
from aqt.reviewer import Reviewer
from aqt.utils import tooltip
from anki.hooks import addHook
from aqt.operations.scheduling import bury_cards, CollectionOp
from anki.collection import OpChangesWithCount

import sqlite3
import random
import os
import time

SECONDS_IN_DAY = 86400

# Path to user_files folder
ADDON_DIR = os.path.dirname(__file__)
ADDON_USER_FILES_DIR = os.path.join(ADDON_DIR, "user_files")
os.makedirs(ADDON_USER_FILES_DIR, exist_ok=True)

DB_PATH = os.path.join(ADDON_USER_FILES_DIR, "bury.db")


var_dump_log_size = 0
var_dump_log_count = 0

def var_dump_log(var: Any) -> None:

    global var_dump_log_size
    global var_dump_log_count

    if var_dump_log_size < (1024 * 1024) and var_dump_log_count < 100_000:
        dump_log_file = os.path.join(os.path.dirname(__file__), 'dump.log')
        with open(dump_log_file, 'a', encoding='utf-8') as file:
            log_entry = pprint.pformat(var, sort_dicts=False, width=160)
            file.write(log_entry + "\n\n=================================================================\n\n")
        var_dump_log_size += len(log_entry)
        var_dump_log_count += 1


def init_db() -> None:
    """Ensure database exists with correct schema."""
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute("""
            CREATE TABLE IF NOT EXISTS buried (
                cid INTEGER PRIMARY KEY,
                until INTEGER
            )
        """)
        c.execute("""
            CREATE INDEX IF NOT EXISTS idx_buried_until ON buried (until)
        """)
        conn.commit()


def parse_days_range(text: str) -> Optional[tuple[int, int]]:
    """Parse input as either a single number or a range, return (low, high)."""
    text = text.strip()
    try:
        if "-" in text:
            low, high = text.split("-", 1)
            low_val, high_val = int(low), int(high)
            if low_val > high_val:
                return None
        else:
            val = int(text)
            low_val, high_val = val, val
    except ValueError:
        return None

    if low_val < 1:
        return None

    return low_val, high_val


def mark_cards_as_n_buried(cids: list[int], days_range: tuple[int, int]) -> None:
    """Mark cards as buried for random number of days in [low, high]."""
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        data = []
        current_time = int(time.time())

        for cid in cids:
            days = random.randint(days_range[0], days_range[1])
            until_ts = current_time + days * SECONDS_IN_DAY
            data.append((cid, until_ts))

        c.executemany(
            "INSERT OR REPLACE INTO buried (cid, until) VALUES (?, ?)", data
        )
        conn.commit()


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


def bury_cards_ui(parent: Union[Browser, Reviewer], cids: list[int]) -> None:
    """Shared UI logic for burying given card IDs."""
    if not cids:
        QMessageBox.information(parent, "Bury N days", "No cards selected.")
        return

    days_range = ask_days_range(parent)
    if not days_range:
        return
    
    op_parent = parent.mw if isinstance(parent, Reviewer) else parent
    
    def _on_success(res: OpChangesWithCount) -> None:
        if res.count == 0:
            return

        if days_range[0] == days_range[1]:
            tooltip("Buried {} card(s) for {} days.".format(len(cids), days_range[0]), parent=op_parent)
        else:
            tooltip(
                "Buried {} card(s) for {} to {} days.".format(len(cids), days_range[0], days_range[1], parent=op_parent)
            )

    mark_cards_as_n_buried(cids, days_range)
    bury_cards(parent=op_parent, card_ids=cids).success(_on_success).run_in_background()




def bury_browser_selected(browser: Browser) -> None:
    """Triggered from Browser context menu."""
    bury_cards_ui(browser, browser.selectedCards())


def bury_reviewer_card(reviewer: Reviewer) -> None:
    """Triggered from Reviewer 'More' menu."""
    if reviewer.card:
        bury_cards_ui(mw, [reviewer.card.id])


def add_action_to_menu(menu: QMenu, new_action: QAction, before_separator_index: int) -> None:
    """Add action before first separator in menu."""
    actions = menu.actions()
    inserted = False
    num_separators = 0
    for act in actions:
        if act.isSeparator():
            num_separators += 1
        if num_separators == before_separator_index:
            menu.insertAction(act, new_action)
            inserted = True
            break

    if not inserted:  # fallback if no separator found
        menu.addAction(new_action)


def add_context_menu(browser: Browser) -> None:
    """Add 'Bury N days' option to Browser context menu."""
    action = QAction("Bury N days", browser)
    action.triggered.connect(lambda _, b=browser: bury_browser_selected(b))
    menu = browser.form.menu_Cards

    # Add before second separator
    add_action_to_menu(menu, action, 2)


def add_reviewer_menu(view: Reviewer, menu: QMenu) -> None:
    """Add 'Bury N days' option to Reviewer More menu, above the first separator."""
    action = QAction("Bury N days", menu)
    action.triggered.connect(lambda _, r=view: bury_reviewer_card(r))

    # Add before first separator
    add_action_to_menu(menu, action, 1)


def cleanup_expired() -> None:
    """Remove expired entries."""
    now = int(time.time())
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute("DELETE FROM buried WHERE until <= ?", (now,))
        conn.commit()


def reapply_buries(use_collection_op: bool) -> None:
    """At Anki startup, re-bury still-active cards."""
    now = int(time.time())

    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute("SELECT cid FROM buried WHERE until > ?", (now,))
        rows = c.fetchall()

        if rows:
            cids = [cid for (cid,) in rows]
            def _show_tooltip(op_result: OpChangesWithCount) -> None:
                if op_result.count > 0:
                    tooltip("Re-buried {} of {} cards.".format(op_result.count, len(cids)), parent=mw)
            if use_collection_op:
                CollectionOp(mw, lambda col: col.sched.bury_cards(cids, manual=False)).success(_show_tooltip).run_in_background()
            else:
                op_result = mw.col.sched.buryCards(cids, manual=False)
                _show_tooltip(op_result)

        # cleanup
        if random.randint(1, 10) == 1:
            cleanup_expired()


# Initialize
init_db()
addHook("browser.setupMenus", add_context_menu)
addHook("profileLoaded", partial(reapply_buries, use_collection_op=False))

try:
    from aqt import gui_hooks

    def on_sync_will_start(*_) -> None:
        reapply_buries(use_collection_op=False)

    def on_sync_finished(*_) -> None:
        reapply_buries(use_collection_op=False)

    gui_hooks.sync_will_start.append(on_sync_will_start)
    gui_hooks.sync_did_finish.append(on_sync_finished)
    gui_hooks.reviewer_will_show_context_menu.append(add_reviewer_menu)

except ImportError:
    # very old Anki, no gui_hooks
    pass

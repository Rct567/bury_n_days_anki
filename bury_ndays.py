from aqt import mw
from aqt.qt import QAction, QInputDialog, QMessageBox
from aqt.browser import Browser
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


def add_context_menu(browser: Browser) -> None:
    """Add 'Bury N days' option to Browser context menu."""
    action = QAction("Bury N days", browser)
    action.triggered.connect(lambda _, b=browser: bury_browser_selected(b))
    browser.form.menu_Cards.addAction(action)
    
    
def mark_cards_as_n_buried(cids: list[int], days: int) -> None:
    """Mark cards as buried for a given number of days."""
    until_ts = int(time.time() + days * 86400)

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    for cid in cids:
        c.execute("INSERT OR REPLACE INTO buried (cid, until) VALUES (?, ?)", (cid, until_ts))
    conn.commit()
    conn.close()


def bury_browser_selected(browser: Browser) -> None:
    """Handle burying of selected cards/notes."""
    cids = browser.selectedCards()
    if not cids:
        QMessageBox.information(browser, "Bury N days", "No cards selected.")
        return

    days, ok = QInputDialog.getInt(browser, "Bury N days",
                                   "Enter number of days:", 1, 1, 365, 1)
    if not ok:
        return

    mark_cards_as_n_buried(cids, days)

    mw.col.sched.buryCards(cids)
    tooltip("Buried {} cards for {} days".format(len(cids), days))


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
        mw.col.sched.buryCards(cids)
        tooltip("Re-buried {} cards".format(len(cids)))
        
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

    def on_sync_finished(*_) -> None:
        reapply_buries()

    gui_hooks.sync_did_finish.append(on_sync_finished)

except ImportError:
    # very old Anki, no gui_hooks
    pass
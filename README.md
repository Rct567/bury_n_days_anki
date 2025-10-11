# Bury N Days – Anki Add-on

This add-on allows you to bury cards in Anki for a specific number of days.

## Features

* Adds **“Bury N days”** option to the Browser and Reviewer context menu.
* Input either:
  * A single number (`10`) → buries for 10 days.
  * A range (`1-100`) → buries cards between 1 and 100 days, evenly distributed based on FSRS's stability or interval.
* Persists buried cards across restarts and syncs.

## Installation

1. Copy this add-on into your Anki `addons21` folder.
2. Restart Anki.

## Usage in the Browser

1. Open the Browser.
2. Select one or more cards.
3. Right-click and choose **“Bury N days”**.
4. Enter a number (e.g., `10`) or a range (e.g., `1-100`).
5. The cards will be buried for the specified duration.

## Notes

* Buried state is tracked in a small SQLite database stored in:

  ```
  user_files/bury.db
  ```
* Occasionally, expired entries are cleaned up automatically.

---

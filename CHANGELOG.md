# Changelog

## 0.7.6 (10 Nov 2026)

- Links and buttons follow a changed Cardlake connection without a restart. Hermes reconnects to a changed `cardlake` connection by itself, but the plugin read the address only when Hermes started, so after switching to a self-hosted copy the cards came from the new copy while Open Cardlake still went to the old one. The address is now read when a link is made (at most every 30 seconds).
- README: what to do when sign-in ends on "site can't be reached"; a catalog install line; a card image for the catalog.
- CI runs Hermes' Plugin Doctor.

## 0.7.5 (10 Nov 2026)

- `/cardlake` now shows in Telegram's `/` menu. Hermes fills that menu with its own commands first and stops at 60, so plugin commands were left out; the plugin now adds `/cardlake` itself after Hermes connects to Telegram, and again after each reconnect. A Telegram menu you've set up yourself in Hermes is left alone.

## 0.7.4 (9 Nov 2026)

- **Fixed: replying "done" to a card and sending a link to save it never worked.** The plugin's own tools were in a toolset named `cardlake`, the name the README gives the Cardlake connection, and Hermes then hid all of Cardlake's tools from the model. The plugin's toolset is now `cardlake-plugin`.
- Hermes is told where Cardlake's tools are, so a plain "save this" finds them without searching files or the terminal.
- A feed longer than one page says "20+ cards" and "…and more in Cardlake" instead of a wrong exact count.
- A snooze that has already run out is no longer shown as "back today".
- Telegram buttons: a second tap while the first is still saving is ignored (it used to save a card twice); a send that times out is stopped; a network error isn't resent as a second copy; when Telegram says to slow down, the plugin waits and sends once more.
- Every push is tested on Python 3.11 to 3.13, against the latest Hermes and through Hermes' plugin validator.
- README: a short film, a screenshot, troubleshooting and how to update.

## 0.7.0 (8 Nov 2026)

- Works with a self-hosted Cardlake: links and buttons follow the address of Hermes' `cardlake` connection, or `CARDLAKE_URL`.

## 0.6.0 (7 Nov 2026)

- `cardlake_show_cards`: Hermes can show its own results (links, videos, findings, a job's report) as cards with Save to Cardlake and Remind me, both with Undo.

## 0.5.0 (7 Nov 2026)

- Feed filters: `/cardlake feed learning`, `reminders`, `work`, `family`, `bookmarks`, `misc`, `github`, `files`, `favorites` and `snoozed` (with Bring back and when each card returns).

## 0.4.0 (7 Nov 2026)

- Buttons on the morning message, a pinned Today checklist that ticks off as you go, Undo on every button, and `/cardlake deal`.

## 0.3.0 (7 Nov 2026)

- Done, Tomorrow and Next week buttons under each card in a private Telegram chat.

## 0.2.0 (7 Nov 2026)

- Cards laid out as Telegram quote panels, `/cardlake today`, and the Cardlake morning blueprint.

## 0.1.0 (7 Nov 2026)

- First version: `/cardlake feed`, `save` and `snooze`, with secrets removed before anything is sent.

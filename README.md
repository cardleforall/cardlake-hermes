# Cardlake for Hermes Agent

Your [Cardlake](https://cardlake.app) cards in [Hermes](https://hermes-agent.nousresearch.com), laid out as cards in Telegram, with what's due sent to you each morning.

You need a free Cardlake account, and nothing to host: the plugin runs inside Hermes and connects to cardlake.app. It doesn't work yet with self-hosted copies of Cardlake.

## Install

```bash
hermes plugins install cardleforall/cardlake-hermes --enable
```

## Sign in

Connect Hermes to Cardlake. Your browser opens so you can sign in:

```bash
hermes mcp add cardlake --url https://cardlake.app/api/mcp --auth oauth
```

Keep the name `cardlake`, and don't add a client name, client id or fixed port: those turn off the sign-in Cardlake accepts. To sign in again later, run `hermes mcp login cardlake`.

This is a separate step because a Hermes plugin with commands can't carry a sign-in connection of its own.

## Commands

| Command | What it does |
| --- | --- |
| `/cardlake feed` | Shows the top of your feed as cards |
| `/cardlake feed <filter>` | Shows just one kind: `reminders`, `learning`, `work`, `family`, `bookmarks`, `misc`, `github`, `files`, `favorites` (cards you've hearted) or `snoozed` (with a Bring back button, and when each card comes back) |
| `/cardlake today` | Shows reminders that are overdue or due today |
| `/cardlake deal` | Deals you five cards to look at again, like the app's Deal me 5: none that are overdue, due today or pinned |
| `/cardlake save <text>` | Saves your text as a card; your model picks the kind |
| `/cardlake snooze <text>` | Snoozes the matching card until tomorrow. If several match, it asks which first |

Days follow your time zone: the `timezone` set in Hermes, otherwise your computer's.

## How cards look

Each card is a quote block, which Telegram shows as a panel: its type, whether it's overdue or due today, a 📌 if it's pinned, the title in bold, and a short link when it has one. The 3 most urgent cards are shown in full (overdue, then due today, then pinned) and the rest get one line each, up to 8.

No boxes or ASCII art, which only line up in a terminal.

### In Telegram

In your private Telegram chat with Hermes, `/cardlake feed`, `today` and `deal` send each card shown in full as its own message, with its buttons right under it: ✅ Done (reminders and learnings), ⏰ Tomorrow and 📅 Next week. The rest of the list follows, with a 🔗 Open Cardlake button.

- **A tap changes only the card above it.** Its buttons then say what happened, with **↩ Undo** next to them. Undo puts the card back as it was, including its pin and, for a reminder, its date.
- **Today comes with a pinned checklist.** `/cardlake today` and the morning message start with a list of what's due, pinned to the top of the chat. Each tap ticks a line off, until it says nothing is left for today. The next one replaces the pin.
- **Learning cards show their video.** A learning card's message previews its link, so a talk or course shows its thumbnail. Other messages show no preview.

Group chats, forum topics, other platforms and Hermes versions without plugin button support get the whole reply as one message instead. Telegram previews the first link in a message, so that message's heading links to Cardlake: the preview under it is Cardlake's, not a video or article from one of your cards. To turn previews off altogether, add this to `~/.hermes/config.yaml` and restart the gateway. It applies to every Telegram message Hermes sends:

```yaml
gateway:
  platforms:
    telegram:
      extra:
        disable_link_previews: true
```

The plugin also tells Hermes to show cards the same way in ordinary replies, such as "what's on my plate?". Models follow this most of the time, not always.

## In chat

- **Reply to update.** Say "done", "tomorrow" or "next week" with a card's name, or in reply to a card, and Hermes updates it. If more than one card matches, it asks which.
- **Forward to save.** Forward a link or a message, or send a voice note, with nothing else, and Hermes saves it as one card: articles, videos and courses as learnings, other links as bookmarks, anything with a date as a reminder, the rest as Misc.
- **Link to your feed.** Every `/cardlake` reply, and any reply in which Hermes used Cardlake, ends with `Open Cardlake: https://cardlake.app/vault/`. Other replies are left alone.

## Morning message

Run `/blueprint`, pick **Cardlake morning**, and choose a time. Each morning it sends your overdue and due-today reminders to your Telegram home channel: in a private chat, as the pinned checklist and cards with buttons described above; elsewhere, as one message laid out as cards. A morning with nothing due sends nothing. It runs once a day, so a reminder due later that afternoon shows up in the next morning's message, not at the time it's due.

The message is laid out by the plugin, not written by the model, so it looks the same every day. It never changes cards; the plugin blocks it from doing so. Keep the job's name as it is, because that's how the plugin recognizes it.

## Privacy and safety

- Passwords, API keys and tokens are removed in code before anything is sent to Cardlake. The removal works by pattern, so it can't promise to catch every secret, and it sometimes removes harmless text that looks like one.
- `/cardlake save` sends your text to the model you already use in Hermes, with those secrets removed. The text is treated as content, never as instructions, and the plugin checks the model's answer: it can only create one card.
- The plugin never reads your past Hermes conversations.

## Tests

```bash
python -m unittest discover -t . -s tests
```

With Hermes installed, it also tests against the real thing; without it, those tests are skipped.

## License

[GNU AGPL-3.0](LICENSE).

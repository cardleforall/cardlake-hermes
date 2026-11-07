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
| `/cardlake today` | Shows reminders that are overdue or due today |
| `/cardlake save <text>` | Saves your text as a card; your model picks the kind |
| `/cardlake snooze <text>` | Snoozes the matching card until tomorrow. If several match, it asks which first |

Days follow your time zone: the `timezone` set in Hermes, otherwise your computer's.

## How cards look

Each card is a quote block, which Telegram shows as a panel: its type, whether it's overdue or due today, a 📌 if it's pinned, the title in bold, and a short link when it has one. The 3 most urgent cards are shown in full (overdue, then due today, then pinned) and the rest get one line each, up to 8.

No boxes or ASCII art, which only line up in a terminal.

In your private Telegram chat with Hermes, `/cardlake feed` and `/cardlake today` also get buttons: for each card shown in full, ✅ to mark it done (reminders and learnings), ⏰ Tomorrow and 📅 Next week to snooze it, and 🔗 Open Cardlake. A tap changes only that card, and its row then says what happened. Buttons are left out in group chats, on other platforms, and on Hermes versions without plugin button support; there you get the same message as text.

Telegram previews the first link in a message, so the heading links to Cardlake: the preview under your feed is Cardlake's, not a video or article from one of your cards. To turn previews off altogether, add this to `~/.hermes/config.yaml` and restart the gateway. It applies to every Telegram message Hermes sends:

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

Run `/blueprint`, pick **Cardlake morning**, and choose a time. Each morning it sends your overdue and due-today reminders to your Telegram home channel, laid out as cards. A morning with nothing due sends nothing. It runs once a day, so a reminder due later that afternoon shows up in the next morning's message, not at the time it's due.

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

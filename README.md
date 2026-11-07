# Cardlake for Hermes Agent

Turn your [Hermes](https://hermes-agent.nousresearch.com) conversations into [Cardlake](https://cardlake.app) cards, only when you ask.

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
| `/cardlake today` | Adds up to 3 cards from today's conversations (midnight to now) |
| `/cardlake yesterday` | The same for yesterday |
| `/cardlake week` | The same for the past 7 days |
| `/cardlake feed` | Shows the top of your feed |
| `/cardlake save <text>` | Saves your text as a card |
| `/cardlake snooze <text>` | Snoozes the matching card until tomorrow. If several match, it asks which first |

The first three go straight to your feed, then list what was added and which conversation each came from. If nothing is useful, they say so and add nothing. A card already in Cardlake with the same title isn't added again.

Days follow your time zone: the `timezone` set in Hermes, otherwise your computer's.

| From the conversation | Card |
| --- | --- |
| To-do | Work item, or a reminder if it has a date |
| Something learned | Learning |
| Decision or open question | Misc |

## Morning briefing

Run `/blueprint`, pick **Cardlake morning briefing**, and choose a time. Each morning it sends a recap of yesterday to your Telegram home channel and offers `/cardlake yesterday`. A day with nothing useful sends no message.

The briefing never adds, edits or deletes cards; the plugin blocks it from doing so. Keep the job's name as it is, because that's how the plugin recognizes it.

## Privacy and safety

- Passwords, API keys and tokens are removed in code before anything is sent to Cardlake. The removal works by pattern, so it can't promise to catch every secret, and it sometimes removes harmless text that looks like one.
- Conversation text also goes to the model you already use in Hermes, with those secrets removed.
- Text in a conversation is treated as content, never as instructions. The model picks cards without access to any tools, and the plugin checks its answer: it can only create up to 3 cards.

## Tests

```bash
python -m unittest discover -t . -s tests
```

With Hermes installed, it also tests against the real thing; without it, those tests are skipped.

## License

[GNU AGPL-3.0](LICENSE).

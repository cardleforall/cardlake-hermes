# Contributing to the Cardlake plugin for Hermes

Thanks for taking a look.

**Issues are welcome; pull requests aren't accepted.** Report bugs and suggest features through the issue templates. The plugin has a single maintainer, and every change is written by them, so please don't open a pull request: it will be closed without review. If you'd like something changed, open an issue describing it instead.

You're free to change your own copy as you like. The rest of this doc covers running the tests.

## Running the tests

The plugin needs nothing but Python 3.11 or newer for its tests:

```bash
git clone https://github.com/cardleforall/cardlake-hermes.git
cd cardlake-hermes
python -m unittest discover -t . -s tests
```

A few tests need Hermes itself and are skipped without it. On GitHub, every push runs them all against the latest Hermes, along with Hermes' own plugin validator (`.github/workflows/tests.yml`).

## How the code is laid out

| File | What it does |
| --- | --- |
| `__init__.py` | Registers the `/cardlake` command, the tools, hooks, chat guide and morning blueprint |
| `commands.py` | What each `/cardlake` command does, and the one function that calls Cardlake |
| `feed_view.py` | Lays cards out as chat text |
| `buttons.py` | Telegram cards with buttons, Undo and the pinned Today checklist |
| `show.py` | `cardlake_show_cards`: Hermes' own results as cards you can save |
| `cards.py` | Turns `/cardlake save` text into one card, checking everything the model returns |
| `redact.py` | Removes passwords, keys and tokens before anything is sent |
| `address.py` | Which Cardlake to link to: cardlake.app or a self-hosted copy |

## Code style

Match the file you're editing: small, well-named functions, and comments that explain *why*. Every change comes with a test.

## Code of Conduct

This project follows the [Contributor Covenant](CODE_OF_CONDUCT.md). Be respectful; disagreements about code are fine, personal attacks aren't.

## License

The plugin is licensed under the [GNU AGPL-3.0](LICENSE).

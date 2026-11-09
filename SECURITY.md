# Security policy

## Reporting a vulnerability

Please don't open a public issue for a security problem. Report it privately
instead, through GitHub's **Report a vulnerability** button on this
repository's Security tab.

Include what you found, how to reproduce it, and what an attacker could do
with it. You'll get an acknowledgement within a few days. Please give us a
reasonable chance to fix it before you disclose it publicly.

## Scope

In scope: this repository's code. Most valuable are findings that let
someone other than the chat's owner change cards through the plugin's
buttons, get a secret past the redaction before it reaches Cardlake, make the
morning job change cards, or make text saved with `/cardlake save` act as
instructions.

Problems in Cardlake itself (cardlake.app, sign-in, stored data) belong to
Cardlake: report them at https://github.com/cardleforall/cardlakeforall.
Problems in Hermes belong to Hermes.

Please test with your own Hermes and your own Cardlake account. Don't test
against other people's chats or data, or use social engineering.

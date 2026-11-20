"""Display Discord names in cards without depending on mention resolution."""
import discord


def account_label(display_name, username):
    display = (display_name or '').strip()
    account = (username or '').strip()
    if display and account and display.casefold() != account.casefold():
        return f'{display}（{account}）'
    return display or account


def member_label(member):
    display = getattr(member, 'display_name', None) or getattr(member, 'global_name', None)
    return account_label(display, getattr(member, 'name', None))


def plain_name(label):
    # An embed interprets angle-bracket entities and Markdown even with pings disabled.
    text = ' '.join(label.split()).replace('<', '＜').replace('>', '＞')
    text = text.replace('://', ':\u200b//')
    return discord.utils.escape_mentions(discord.utils.escape_markdown(text, ignore_links=False))

"""Keep functional channel lookup compatible with approved display emoji suffixes."""
import unicodedata


def plain_channel_name(name):
    # Only edge decoration: preserve all internal text, punctuation and game names.
    def decoration(char):
        return char.isspace() or char in '|｜' or unicodedata.category(char)[0] in ('S', 'M') or unicodedata.category(char)=='Cf'
    while name and decoration(name[0]):name=name[1:]
    while name and decoration(name[-1]):name=name[:-1]
    return name


def is_squad_chat_name(name):
    return name.removesuffix('💬').rstrip().endswith('-吹水組隊')

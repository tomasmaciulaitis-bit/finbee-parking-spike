"""Lithuanian wording for dates, shared by notifications and pages."""

WEEKDAYS = ("pirmadienis", "antradienis", "trečiadienis", "ketvirtadienis", "penktadienis",
            "šeštadienis", "sekmadienis")
MONTHS = ("sausio", "vasario", "kovo", "balandžio", "gegužės", "birželio", "liepos", "rugpjūčio",
          "rugsėjo", "spalio", "lapkričio", "gruodžio")


def day_label(day):
    """'antradienis, spalio 6 d.'"""
    return "%s, %s %d d." % (WEEKDAYS[day.weekday()], MONTHS[day.month - 1], day.day)


def sentence(text):
    return text[:1].upper() + text[1:]

"""Lithuanian wording for dates and phone numbers, shared by notifications and pages."""

WEEKDAYS = ("pirmadienis", "antradienis", "trečiadienis", "ketvirtadienis", "penktadienis",
            "šeštadienis", "sekmadienis")
MONTHS = ("sausio", "vasario", "kovo", "balandžio", "gegužės", "birželio", "liepos", "rugpjūčio",
          "rugsėjo", "spalio", "lapkričio", "gruodžio")


def day_label(day):
    """'antradienis, spalio 6 d.'"""
    return "%s, %s %d d." % (WEEKDAYS[day.weekday()], MONTHS[day.month - 1], day.day)


def sentence(text):
    return text[:1].upper() + text[1:]


def phone(number):
    """'+37061234567' → '+370 612 34567'; another country's number as stored."""
    if number and number.startswith("+370") and len(number) == 12:
        return "%s %s %s" % (number[:4], number[4:7], number[7:])
    return number or ""

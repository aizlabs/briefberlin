"""Shared lexical normalization for story and edition matching."""

import re
import unicodedata

STOPWORDS = set("der die das den dem des ein eine einer einem einen eines und oder für mit bei aus "
                "sich von auf an am ist sind wird werden berlin berliner berlinerin nach im zum "
                "the and with for from".split())


def words(value: str) -> set[str]:
    value = "".join(c for c in unicodedata.normalize("NFKD", value.casefold())
                    if not unicodedata.combining(c))
    return {w for w in re.findall(r"[a-z0-9]+", value)
            if len(w) > 2 and w not in STOPWORDS}
